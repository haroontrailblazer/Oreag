import hashlib
import json
import logging
import math
import re
import time
import uuid
from datetime import date, datetime, timezone
from typing import NamedTuple

import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import delete as sql_delete
from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import Chunk, File, Project
from ..providers.base import usage_from_openai
from ..schemas import (
    DEFAULT_RELATION,
    INSTRUMENT_ROLES,
    LEGAL_STATUSES,
    RELATION_KINDS,
    RELATIONS,
)
from . import embedding_usage
from .usage import record_usage
from ..providers import registry, resolver
from ..providers.registry import (
    embed_batch_size,
    get_embedder,
    prefix_normalize,
)
from . import storage
from . import document_events
from .content_version import bump_content_version
from .conversion import (
    AUDIO_EXTENSIONS,
    CONVERSION_VERSION,
    IMAGE_CAPTION_EXTENSIONS,
    ConvertedDocument,
    convert_to_markdown,
    markdown_path_for,
    source_extension,
)

logger = logging.getLogger(__name__)

# Gemini's OpenAI-compatible surface - lets MarkItDown's captioning (which
# speaks the OpenAI chat-completions format) run on Gemini keys too.
GEMINI_OPENAI_COMPAT_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"



class _MeteredVisionClient:
    """Wraps the OpenAI client handed to MarkItDown so captioning is metered.

    MarkItDown makes the captioning call ITSELF - we only supply the client -
    so there is no return value to read `usage` from. Intercepting
    `chat.completions.create` is the only place the response is visible.

    Delegates everything else untouched via __getattr__, so this stays correct
    if MarkItDown starts using another part of the client.

    Image captioning was the last unmetered spend in the product, and it is not
    small: a scanned PDF captions EVERY page through a vision model, which for
    an image-heavy document costs more than embedding it.
    """

    def __init__(self, client, model: str):
        self._client = client
        self._model = model
        self.chat = _MeteredChat(client.chat, model)

    def __getattr__(self, name):
        return getattr(self._client, name)


class _MeteredChat:
    def __init__(self, chat, model: str):
        self._chat = chat
        self.completions = _MeteredCompletions(chat.completions, model)

    def __getattr__(self, name):
        return getattr(self._chat, name)


class _MeteredCompletions:
    def __init__(self, completions, model: str):
        self._completions = completions
        self._model = model

    def create(self, *args, **kwargs):
        resp = self._completions.create(*args, **kwargs)
        try:
            embedding_usage.record_llm(
                usage_from_openai(resp, kwargs.get("model") or self._model)
            )
        except Exception:
            logger.debug("Could not meter a captioning call", exc_info=True)
        return resp

    def __getattr__(self, name):
        return getattr(self._completions, name)


def vision_llm_for(project: Project, api_key: str | None):
    """(client, model) for MarkItDown image captioning, or (None, None).

    Reuses the project's ANSWER model: OpenAI chat models and all Gemini
    models are vision-capable and both speak the OpenAI wire format MarkItDown
    expects. Other providers (Anthropic, local, compat vendors) don't fit that
    slot, so their projects skip captioning and image ingestion fails with a
    clear message instead of a provider 400.
    """
    if not api_key:
        return None, None
    if project.llm_provider == "openai":
        from ..providers.openai_provider import GENERATE_TIMEOUT, MAX_RETRIES

        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=GENERATE_TIMEOUT, max_retries=MAX_RETRIES)
        return _MeteredVisionClient(client, project.llm_model), project.llm_model
    if project.llm_provider == "gemini":
        # No key-prefix skip here. "AQ." keys used to be refused captioning
        # outright on the belief they were Vertex-only; they are ordinary AI
        # Studio keys and authenticate fine against this endpoint, so the skip
        # was a pure false negative - it silently disabled image captioning
        # for every user with a modern Gemini key, and conversion.py then
        # reported "No text could be extracted".
        from ..providers.openai_provider import GENERATE_TIMEOUT, MAX_RETRIES

        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=GEMINI_OPENAI_COMPAT_URL,
            timeout=GENERATE_TIMEOUT,
            max_retries=MAX_RETRIES,
        )
        return _MeteredVisionClient(client, project.llm_model), project.llm_model
    return None, None


def audio_transcribers_for(db: Session, project: Project) -> list[tuple[str, object]]:
    """Ordered BYOK transcription chain from the uploader's own keys.

    Every STT-capable provider the uploader holds a key for (project override
    or account key) gets a slot, the project's own answer-model provider
    first - so a Gemini project transcribes with the user's Gemini key, a
    Sarvam project with Saarika, and so on. An empty chain (or every entry
    failing) means conversion falls back to the free Google endpoint.
    """
    from ..providers import transcription

    chain: list[tuple[str, object]] = []
    ordered = [project.llm_provider] + [
        p for p in transcription.STT_PROVIDERS if p != project.llm_provider
    ]
    for provider in ordered:
        if provider not in transcription.STT_PROVIDERS:
            continue
        api_key = resolver.resolve_key_for_provider(db, project, provider)
        if not api_key:
            continue
        gemini_model = (
            project.llm_model
            if provider == "gemini" and project.llm_provider == "gemini"
            else transcription.DEFAULT_GEMINI_STT_MODEL
        )
        transcriber = transcription.transcriber_for(
            provider, api_key, gemini_model=gemini_model
        )
        if transcriber is not None:
            chain.append((provider, transcriber))
    return chain


def parse_pdf(data: bytes) -> list[tuple[int, str]]:
    """Returns (1-based page number, text) for every page with text."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()
            if text:
                pages.append((i + 1, text))
        return pages
    finally:
        doc.close()


def recompute_project_status(db: Session, project: Project) -> None:
    # the session runs with autoflush=False, so flush pending file status
    # changes/deletes first - otherwise this SELECT reads stale rows.
    db.flush()
    # chunk_count and in_force_to ride along in the same round trip: since
    # migration 0034 a file can exist and hold no chunks without having failed.
    rows = db.execute(
        select(File.status, File.chunk_count, File.in_force_to).where(
            File.project_id == project.id
        )
    ).all()
    statuses = {r.status for r in rows}
    if not statuses:
        project.status = "empty"
    elif statuses & {"pending", "processing"}:
        project.status = "indexing"
    elif any(r.status == "failed" and r.in_force_to is None for r in rows):
        # Superseded rows are excluded from the failure check. A retired edition
        # that failed to index is not a problem with the project - it holds no
        # chunks by design, retrying it is refused by design, and deleting it
        # would destroy the history this feature exists to keep. Counting it
        # would pin the project at 'error' with no action available to clear it.
        project.status = "error"
    elif not any(r.in_force_to is None and r.chunk_count > 0 for r in rows):
        # Files exist but NOTHING is searchable - every one is parked in review
        # or superseded. "ready" has always implied at least one indexed chunk
        # (ingestion raises "Document produced no chunks" before it can reach
        # 'indexed'), so reporting it here would tell /v1 and the dashboard the
        # project can answer when it provably cannot. "empty" is the existing
        # value that already means "nothing to answer from", so this needs no
        # new project status, no ProjectOut field and no docs change.
        project.status = "empty"
    else:
        project.status = "ready"


def _file_still_exists(db: Session, file_id: uuid.UUID) -> bool:
    """Fresh SELECT (bypasses the identity map): the user may delete the file
    from another session while ingestion is mid-flight."""
    return db.scalar(select(File.id).where(File.id == file_id)) is not None


def _file_still_current(db: Session, file_id: uuid.UUID) -> bool:
    """False once this file has been superseded (migration 0034).

    Distinct from _file_still_exists, which cannot detect this: a superseded
    row is very much still there. A worker claims a row and commits that claim
    immediately, holding no lock for the length of the ingest, so a confirm can
    retire the file underneath a pass that is already running.

    `.first()` on the tuple rather than `db.scalar`, because the value being
    read is legitimately NULL for a current file and scalar() cannot tell that
    apart from "no such row".
    """
    row = db.execute(select(File.in_force_to).where(File.id == file_id)).first()
    return row is not None and row[0] is None


def mark_file_failed(db: Session, file_id: uuid.UUID, message: str) -> None:
    """Best-effort failure marking that NEVER raises.

    The file may have been deleted mid-ingestion; after a rollback, db.get()
    would happily return the stale identity-map object and the follow-up
    commit would explode inside the error handler. An exception escaping this
    background task aborts every queued ingestion behind it - the "delete a
    waiting file and the backend dies" bug.
    """
    try:
        db.rollback()
        db.expunge_all()  # drop stale identity-map entries so get() hits the DB
        file = db.get(File, file_id)
        if file is None:
            logger.info("File %s was deleted during ingestion - skipping", file_id)
            return
        file.status = "failed"
        file.error = message[:500]
        document_events.record_safely(
            db, file.project_id, "ingest_failed",
            file_id=file.id, document_id=file.document_id,
            filename=file.filename, error=message[:300],
        )
        file.conversion_error = message[:500]
        file.conversion_note = None  # a failed file's caveat would only confuse
        # A failed ingest may have committed some chunk batches before dying -
        # drop them so retrieval never serves half-indexed content.
        db.execute(sql_delete(Chunk).where(Chunk.file_id == file.id))
        bump_content_version(db, file.project_id)
        project = db.get(Project, file.project_id)
        if project is not None:
            recompute_project_status(db, project)
        db.commit()
    except Exception:
        logger.exception("Could not mark file %s as failed", file_id)
        db.rollback()


def _reuse_converted_markdown(file: File) -> str | None:
    """Previously converted markdown for this file, or None to convert again.

    Returns None - meaning "just convert it" - for every uncertain case:
      * no markdown was ever stored,
      * it was written by a DIFFERENT conversion pipeline (see
        CONVERSION_VERSION), so it may carry a bug that has since been fixed,
      * the column does not exist yet because migration 0023 has not run,
      * the blob is missing, unreadable, or decodes to nothing.

    Fails open on purpose. This is an optimisation; the correct behaviour when
    anything is unclear is the slower path that definitely works, never a
    failed ingest. An empty result is treated as absent rather than as "this
    file has no text", which would wrongly mark it indexed with zero chunks.
    """
    if not file.markdown_storage_path:
        return None
    try:
        if file.conversion_version != CONVERSION_VERSION:
            return None
    except Exception:  # column missing - migration 0023 not applied
        return None
    try:
        markdown = storage.download(file.markdown_storage_path).decode("utf-8")
    except Exception:
        logger.info(
            "Stored markdown for file %s is unreadable - converting again",
            file.id,
        )
        return None
    return markdown.strip() or None


def ingest_file(file_id: uuid.UUID) -> None:
    """Background task: parse -> chunk -> embed -> store, with status updates.

    Runs in Starlette's threadpool (sync def), so it owns its DB session.

    Metered here rather than at the upload route. The route returns as soon as
    the file is queued; the embedding happens later on an ingest WORKER thread,
    which is outside the HTTP request the usage middleware wraps - so a UI
    upload was writing its vectors and recording no tokens at all. Ingesting
    one document embeds every chunk of it and is routinely the largest single
    cost in the product, so it is exactly the spend that must not be invisible.
    """
    started = time.perf_counter()
    with embedding_usage.scope() as _embedding:
        try:
            _ingest_file_inner(file_id)
        finally:
            # In a finally: a file that fails PART way through has still paid
            # for whatever it embedded before failing, and that spend is just
            # as real as a successful one.
            _record_ingest_usage(
                file_id, _embedding,
                int((time.perf_counter() - started) * 1000),
            )


def _record_ingest_usage(file_id: uuid.UUID, embedding, latency_ms=None) -> None:
    """Write the usage row for one ingest. Never raises - see services/usage."""
    # EITHER side is enough to be worth a row: an audio file spends only on
    # transcription and embeds a short transcript; an image-heavy PDF spends
    # most of its money on captioning.
    if embedding is None or not (
        embedding.total.known or embedding.llm_total.known
    ):
        return
    db = SessionLocal()
    try:
        file = db.get(File, file_id)
        if file is None:
            return
        project = db.get(Project, file.project_id)
        if project is None:
            return
        record_usage(
            db,
            project=project,
            # No API key: ingestion is triggered by an owner through the
            # dashboard or the upload endpoint, and attributing it to a key
            # would misreport which key spent the money.
            api_key_id=None,
            endpoint="file_ingest",
            # How long indexing this file actually took. Usually the slowest
            # thing the product does, and it carried no timing at all.
            latency_ms=latency_ms,
            embedding=embedding.total,
            # Image captioning and audio transcription: real chat calls on the
            # user's own key, priced by the chat table. They were the last
            # unmetered spend in the product.
            usage=embedding.llm_total if embedding.llm_total.known else None,
        )
        # Stamped on the file too, not only on the usage row: a Matryoshka
        # grow-back restores THIS file's vectors from the archive and needs to
        # know what re-embedding it would have cost. That figure cannot be
        # computed at restore time without doing the very work being avoided,
        # so it has to be remembered here.
        file.embedding_tokens = embedding.total.prompt_tokens
        db.commit()
    except Exception:
        logger.warning("Could not record ingest usage for %s", file_id, exc_info=True)
    finally:
        db.close()


_VERSION_CANDIDATE_LIMIT = 12
_WORD_RE = re.compile(r"[a-z0-9]+")
_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.M)
# Legal boilerplate. Without it every filename containing "Act" and "Rules"
# scores identically, which is most of a statutory corpus.
_VERSION_STOPWORDS = frozenset({
    "the", "of", "act", "and", "in", "to", "for", "a", "an", "no", "rules",
    "regulations", "amendment", "amended", "final", "copy", "draft", "version",
    "pdf", "docx", "doc", "scan", "scanned", "gazette", "notification",
    "order", "part", "chapter", "schedule",
})

# Roles whose whole purpose is to refer to ANOTHER document rather than to
# replace it. Measured over 105 realistic documents, letting these supersede
# was the single largest source of destructive proposals: a correction notice
# retiring the article it corrects, a translation retiring the authoritative
# language edition, an amending Act retiring the principal instrument and
# leaving the index holding only diff text. `unknown` and NULL are absent on
# purpose - a corpus with no role information behaves exactly as before.
NON_SUPERSEDING_ROLES = frozenset({"amending", "correction", "translation", "supplement"})

_VERSION_SYSTEM_PROMPT = (
    "You identify legal, regulatory, scientific and technical documents. You "
    "are given the opening of a new document and a numbered list of documents "
    "already held. Reply with ONE JSON object and nothing else:\n"
    '{"match": <list number, or null>, "version_label": <string or null>, '
    '"in_force_from": <"YYYY-MM-DD" or null>, '
    '"legal_status": "in_force"|"amended"|"repealed"|"draft"|"unknown", '
    '"instrument_role": "principal"|"consolidated"|"amending"|"correction"'
    '|"translation"|"supplement"|"unknown", '
    '"relation_kind": "supersedes"|"restates"|"amends"|"corrects"|"retracts"'
    '|"translates"|"supplements"|"succeeds"|null}\n'
    "\n"
    "instrument_role describes what KIND of document the NEW one is. The "
    "decisive question is whether it CONTAINS the thing it relates to, or "
    "only talks about it:\n"
    "  principal    - a standalone document, complete in itself\n"
    "  consolidated - the COMPLETE text of something, restated. An instrument "
    "as amended up to a date; a later edition, revision or reprint; a journal "
    "version of a preprint; a final report replacing an interim one; an "
    "amended-and-restated agreement. Use this whenever the document "
    "reproduces the whole thing in its new form, however it is titled.\n"
    "  amending     - contains ONLY instructions to change another document "
    "('in section 135, for the words X substitute Y') and does NOT reproduce "
    "the full text of what it changes\n"
    "  correction   - a short notice ABOUT another document: erratum, "
    "corrigendum, Department of Error, retraction notice\n"
    "  translation  - the same edition of a document in another language\n"
    "  supplement   - material accompanying another document: appendix, "
    "supplementary material, annex published separately\n"
    "If the document contains the complete text of the thing it relates to it "
    "is principal or consolidated - NEVER amending, correction or supplement. "
    "A title containing the word 'amendment' does not by itself make a "
    "document amending: an Amendment Act that reproduces the whole amended "
    "statute is consolidated. Judge from the document body, not the title.\n"
    "\n"
    "Set match when the new document is ABOUT one of the listed documents - a "
    "later version of it, an amendment to it, a correction or retraction of "
    "it, a translation of it, a part of it, or the next one in the same "
    "series. Use null when it is simply a different document, and when you are "
    "not sure.\n"
    "\n"
    "relation_kind says what the new document DOES to the one you matched. It "
    "decides whether that document keeps answering questions, so choose it "
    "carefully:\n"
    "  supersedes  - replaces it; a reader should now read this INSTEAD. A "
    "consolidated reprint, a re-enacting statute, a new edition of a standard, "
    "the journal version of a preprint.\n"
    "  restates    - replaces it by setting out the whole thing afresh: an "
    "amended-and-restated agreement, a full revision.\n"
    "  amends      - changes it by instruction without reproducing it. The "
    "document you matched is still the operative text.\n"
    "  corrects    - is a notice about it: erratum, corrigendum, Department of "
    "Error.\n"
    "  retracts    - withdraws it: a retraction notice.\n"
    "  translates  - is the same edition of it in another language.\n"
    "  supplements - is a part of it: appendix, annex, supplementary "
    "material.\n"
    "  succeeds    - is the next one along while the earlier remains valid: "
    "the following year in an annual series, a CFR or standard edition "
    "published yearly, an API version whose predecessor is still supported, an "
    "amendment layered onto a contract that stays in force.\n"
    "Prefer succeeds over supersedes whenever the earlier document is "
    "plausibly still in use. Use supersedes only when the earlier one is "
    "genuinely no longer the thing to read.\n"
    "The same test decides amends: does the new document CONTAIN what it "
    "matched, or only talk about it? If it sets out the whole thing - however "
    "its title reads - it is supersedes, restates or succeeds, never amends. "
    "An Act or an agreement titled 'Amendment' that reproduces the entire "
    "amended text restates it.\n"
    "\n"
    "version_label is how this edition names itself, for example 'Act 18 of "
    "2013', 'Second Amendment 2019', 'Reprint No. 4', 'v2', '4th edition'. "
    "in_force_from is the date this edition takes effect, not the date it was "
    "printed, gazetted or assented to. Use null for anything the document does "
    "not state."
)


class VersionProposal(NamedTuple):
    document_id: uuid.UUID  # NEVER None - the file's own id when standalone
    version_label: str | None
    in_force_from: date | None
    legal_status: str | None
    instrument_role: str | None = None
    # What the new document does to the one it matched. None when nothing
    # matched; read as 'supersedes' when a relation exists but the model did
    # not name one, which is the pre-0037 behaviour.
    relation_kind: str | None = None
    # Why no match was proposed, when the model wanted one. Surfaced to the
    # reviewer so a refusal reads as a decision rather than as the extractor
    # having found nothing.
    refused: str | None = None


def _tokens(text: str) -> set[str]:
    return {
        w for w in _WORD_RE.findall(text.lower())
        if len(w) > 1 and w not in _VERSION_STOPWORDS
    }


def backfill_extracted_titles(project_id: uuid.UUID, limit: int = 1000) -> int:
    """Give the files a project ALREADY holds a title the shortlist can see.

    Turning version tracking on mid-project has to work with what is there, and
    what is there was ingested before extracted_title existed: `document_id IS
    NULL AND indexed_at IS NULL` gates extraction to a file's FIRST index, so an
    already-indexed file is never re-examined and would keep a null title
    forever.

    Those files are already valid match candidates - the candidate query filters
    on in_force_to and status, not on document_id - but stage one can only score
    `filename + version_label + extracted_title`, so a corpus of
    Companies_Act.pdf and scan_0001.pdf offers almost nothing to match against.
    Measured over a realistic corpus that was the dominant reason a true
    predecessor never reached the model at all.

    Cheap by construction: reads the markdown blob each file already has and
    runs one regex. No LLM call, no embedding, no re-conversion, nothing
    written but the title. Runs in the background off the PATCH that flips the
    toggle, and is safe to run again - it only touches rows whose title is
    still null.
    """
    db = SessionLocal()
    filled = 0
    try:
        rows = db.scalars(
            select(File).where(
                File.project_id == project_id,
                File.extracted_title.is_(None),
                File.markdown_storage_path.isnot(None),
                File.in_force_to.is_(None),
            ).limit(limit)
        ).all()
        for file in rows:
            try:
                markdown = storage.download(file.markdown_storage_path)
            except Exception:
                # A missing blob is not worth failing the sweep over - the file
                # simply keeps matching on its filename alone, as it did before.
                logger.info("No markdown for %s during title backfill", file.id)
                continue
            title = _extracted_title(markdown.decode("utf-8", "replace"))
            if title:
                file.extracted_title = title
                filled += 1
        if filled:
            db.commit()
        logger.info(
            "Backfilled %d/%d extracted titles for project %s",
            filled, len(rows), project_id,
        )
    except Exception:
        logger.warning("Title backfill failed for %s", project_id, exc_info=True)
        db.rollback()
    finally:
        db.close()
    return filled


def find_duplicate(db: Session, project_id: uuid.UUID, digest: str):
    """A live file in this project holding byte-identical content, or None.

    0035 recorded content_sha256 and never consulted it, so re-uploading an
    unchanged document created a second row, paid to embed the same text again,
    and - with version tracking on - offered it as a NEW EDITION of the
    document it is byte-identical to. Retiring a document in favour of an
    identical copy of itself is the emptiest possible supersession.

    Superseded rows are excluded: an old edition may legitimately share bytes
    with something being uploaded now (a reinstatement, a re-upload of history),
    and matching against retired content would block that.
    """
    if not digest:
        return None
    return db.scalars(
        select(File).where(
            File.project_id == project_id,
            File.content_sha256 == digest,
            File.in_force_to.is_(None),
        ).limit(1)
    ).first()


def _extracted_title(markdown: str) -> str | None:
    """The document's own first heading, or None.

    Persisted on the row so that the NEXT upload's shortlist can score against
    it. Stage one can only see `filename + version_label` of a held document,
    so a file stored as scan_0001.pdf or Document (7).pdf contributes almost no
    tokens and is unreachable however obviously its text identifies it. Over a
    realistic corpus that was the dominant reason a true predecessor never
    reached the model at all.
    """
    heading = _HEADING_RE.search(markdown[:4000])
    return heading.group(1).strip()[:300] if heading else None


def _probe_text(filename: str, markdown: str) -> str:
    """What identifies an instrument: its filename plus its first heading.

    Scanned filings arrive as scan_0001.pdf and carry their identity only in
    the text, so the heading is pulled out EXPLICITLY rather than taking a raw
    prefix of the markdown, which is mostly gazette boilerplate.
    """
    heading = _HEADING_RE.search(markdown[:4000])
    return f"{filename} {heading.group(1) if heading else markdown[:200]}"


def _shortlist(candidates, probe: str, limit: int = _VERSION_CANDIDATE_LIMIT):
    """The `limit` candidates most likely to be the same instrument.

    Takes anything with .filename and .version_label, so it is unit-testable
    against a NamedTuple with no database - which is the only kind of test this
    CI can run. A project holding fewer than `limit` current documents sends
    all of them regardless of score.

    OVERLAP COEFFICIENT, not Jaccard. After stopwords, "Companies Act 2013" vs
    "Companies Amendment Act 2019" is {companies, 2013} vs {companies, 2019}:
    Jaccard scores that 0.33 and ranks it below noise; overlap scores it 0.5.
    Recall-oriented on purpose - the LLM is the precision filter and the human
    is the gate. No embedding search: that would spend the user's money on
    every upload, and chunk CONTENT is not what identifies an instrument.
    """
    if len(candidates) <= limit:
        return list(candidates)
    probe_tokens = _tokens(probe)
    if not probe_tokens:
        return sorted(candidates, key=lambda r: r.filename)[:limit]

    def score(row) -> float:
        cand = _tokens(
            f"{row.filename} {row.version_label or ''} {row.extracted_title or ''}"
        )
        if not cand:
            return 0.0
        return len(probe_tokens & cand) / min(len(probe_tokens), len(cand))

    # Ties break on RECENCY, then filename. Alphabetical order alone is a
    # coin toss that correlates with nothing: in a corpus of parts named
    # Reg_A_part1..part4 every candidate scores identically, and the shortlist
    # then keeps whichever names sort first rather than whichever is plausibly
    # the predecessor. Filename remains the final key so the result stays
    # deterministic across runs.
    return sorted(
        candidates,
        key=lambda r: (
            -score(r),
            -(r.in_force_from.toordinal() if r.in_force_from else 0),
            r.filename,
        ),
    )[:limit]


def _parse_version_json(reply: str, shortlist):
    """(matched file id, label, date, status) from the model's reply.

    Every branch degrades to None. An unusable reply must mean "no match",
    which is today's behaviour, never a failed ingest.
    """
    try:
        parsed = json.loads(reply.strip())
    except Exception:
        found = re.search(r"\{.*\}", reply, re.S)  # fenced or prefaced JSON
        try:
            parsed = json.loads(found.group(0)) if found else None
        except Exception:
            parsed = None
    if not isinstance(parsed, dict):
        return None, None, None, None, None, None

    matched = None
    index = parsed.get("match")
    # `not isinstance(index, bool)` matters: True is an int and would select [1].
    if isinstance(index, int) and not isinstance(index, bool):
        if 1 <= index <= len(shortlist):
            matched = shortlist[index - 1].id

    label = parsed.get("version_label")
    label = label.strip()[:200] if isinstance(label, str) and label.strip() else None

    from_date = None
    raw = parsed.get("in_force_from")
    if isinstance(raw, str) and len(raw.strip()) == 10:
        try:
            # date.fromisoformat is a REAL calendar check - it rejects
            # 2019-02-30 - and it is stdlib, so nothing is added to
            # requirements.txt. The `date` type then flows unconverted the whole
            # way: model -> date column -> Pydantic date -> ISO string in JSON.
            from_date = date.fromisoformat(raw.strip())
        except ValueError:
            from_date = None

    status = parsed.get("legal_status")
    status = status if status in LEGAL_STATUSES else None

    role = parsed.get("instrument_role")
    role = role if role in INSTRUMENT_ROLES else None

    kind = parsed.get("relation_kind")
    kind = kind if kind in RELATION_KINDS else None
    return matched, label, from_date, status, role, kind


def _propose_version(db: Session, file, project, markdown: str) -> VersionProposal:
    """What this file is a version of, if anything. NEVER raises.

    document_id is ALWAYS set on the way out - the file's own id when nothing
    matched. That is what makes extraction exactly-once: the caller writes it,
    and the gate (`document_id is None`) closes permanently.

    Fail-open is the whole posture. The worst extraction failure - no key, a
    dead provider, a garbled reply - produces exactly the behaviour that
    existed before 0034: index it as its own document. The gate is a positive
    assertion ("this replaces THAT file"), never an absence, so a provider
    outage cannot park a corpus.
    """
    standalone = VersionProposal(file.id, None, None, None)
    # BOTH switches. The per-project flag is the opt-in; the global one is the
    # fleet-wide kill switch. Neither is redundant.
    if not (settings.version_extraction_enabled and project.version_tracking):
        return standalone
    try:
        candidates = db.execute(
            select(
                File.id, File.document_id, File.filename,
                File.version_label, File.in_force_from, File.extracted_title,
            ).where(
                File.project_id == file.project_id,
                File.id != file.id,
                # One row per lineage: the version endpoint keeps at most one
                # file per lineage with a null in_force_to.
                File.in_force_to.is_(None),
                # An unconfirmed proposal is not something to be a version of.
                File.status != "review",
            )
        ).all()
        if not candidates:
            return standalone  # nothing to match against - NO LLM call
        shortlist = _shortlist(candidates, _probe_text(file.filename, markdown))
        # A PINNED model when the deployment names one, the project's answer
        # model otherwise. The answer model is chosen for question-answering,
        # price or latency; letting that incidental choice decide how often the
        # product proposes destroying content is how the same corpus produced
        # 28 false matches on one model and 0 on another. The key is still the
        # project's own - only the judgement is standardised.
        llm = registry.get_llm(
            settings.version_extraction_provider or project.llm_provider,
            settings.version_extraction_model or project.llm_model,
            resolver.resolve_llm_key(db, project),
        )
        listing = "\n".join(
            f"[{i + 1}] {r.filename} | {r.version_label or '-'} | "
            f"{r.in_force_from.isoformat() if r.in_force_from else '-'}"
            for i, r in enumerate(shortlist)
        )
        reply, usage = llm.generate_with_usage(
            _VERSION_SYSTEM_PROMPT,
            f"Existing documents:\n{listing}\n\n"
            f"New document (opening):\n{markdown[:settings.version_extract_chars]}",
        )
        # Metered by the ingest scope this already runs inside - the same
        # accumulator image captioning and audio transcription write into. Zero
        # new metering code, no new usage endpoint label, and the tokens land on
        # the existing file_ingest row priced by the chat table.
        embedding_usage.record_llm(usage)
        matched, label, from_date, status, role, kind = _parse_version_json(
            reply, shortlist
        )
    except Exception:
        logger.info(
            "Version extraction unavailable for file %s", file.id, exc_info=True
        )
        return standalone
    if matched is not None:
        # ONE narrow contradiction is worth overriding: `consolidated` is a
        # positive claim that this document sets out the whole of what it
        # matched, and `amends` claims the opposite. An Act or agreement titled
        # "Amendment" that reproduces the entire amended text restates it, and
        # the model reaches for `amends` on the title alone.
        #
        # Narrow ON PURPOSE, and measured. A wider version of this rule -
        # overriding whenever the role was `principal` - made things worse in
        # both directions, because `principal` turns out to be the model's
        # default label: it applied it to a translation, a meta-analysis, a
        # journal editorial, a proxy statement and a commencement notification.
        # It carries almost no information and must never override a relation.
        # `consolidated` does, so this trusts only that.
        if role == "consolidated" and kind == "amends":
            logger.info(
                "Rewriting relation for consolidated file %s: amends -> restates",
                file.id,
            )
            kind = "restates"
        # A document whose ROLE says it refers to another cannot claim a
        # RETIRING relation, whatever the model picked. Before 0037 the only
        # relation was "supersedes", so the guard had to refuse the match
        # outright; now there is a correct relation for each of these, and the
        # link is kept instead of thrown away.
        if role in NON_SUPERSEDING_ROLES and RELATIONS.get(
            kind or DEFAULT_RELATION, (True,)
        )[0]:
            corrected = {
                "amending": "amends",
                "correction": "corrects",
                "translation": "translates",
                "supplement": "supplements",
            }[role]
            logger.info(
                "Rewriting relation for %s file %s: %s -> %s",
                role, file.id, kind or DEFAULT_RELATION, corrected,
            )
            kind = corrected
    if matched is None:
        # No lineage, but keep whatever the model did read off the document.
        return VersionProposal(file.id, label, from_date, status, role)
    row = next(r for r in shortlist if r.id == matched)
    return VersionProposal(
        row.document_id or row.id, label, from_date, status, role,
        relation_kind=kind or DEFAULT_RELATION,
    )


def _ingest_file_inner(file_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        file = db.get(File, file_id)
        if file is None:
            return
        # A superseded version holds zero chunks BY DEFINITION (migration
        # 0034), so indexing one would put retired content back into search.
        # This sits before the 'processing' write so a stale claim - a worker
        # that took this row just before a confirm superseded it - writes
        # nothing at all rather than leaving a half-touched row behind.
        if file.in_force_to is not None:
            logger.info("File %s is a superseded version - not indexing", file_id)
            return
        project = db.get(Project, file.project_id)
        file.status = "processing"
        file.error = None
        project.status = "indexing"
        db.commit()

        # Reuse the markdown from a previous pass when this file has already
        # been converted by THIS pipeline. A re-embed (model switch, or growing
        # a Matryoshka dimension) has to recompute vectors, but the conversion
        # that produced the text is unchanged - and for images and audio that
        # step costs real money on the user's own keys, so repeating it is a
        # second bill for the same work.
        #
        # Only when the version matches: markdown written by an older pipeline
        # may carry a bug that has since been fixed (the 0x00 bytes strip_nul
        # now removes, for one), and silently re-serving it would undo the fix.
        cached_markdown = _reuse_converted_markdown(file)
        if cached_markdown is not None:
            converted = ConvertedDocument(
                markdown=cached_markdown,
                # Both already live on the row from the original conversion;
                # re-deriving them is exactly the work being skipped.
                page_count=file.page_count,
                note=file.conversion_note,
            )
            logger.info("Reusing converted markdown for file %s", file_id)
            source_bytes = None
        else:
            source_bytes = storage.download(file.storage_path)
        # Rich-media conversion runs on the uploader's own keys (BYOK):
        #   images -> AI caption via the project's answer model (OpenAI/Gemini
        #            speak the OpenAI format MarkItDown's captioner expects);
        #   audio  -> speech-to-text through whichever STT-capable provider
        #            keys the uploader holds (own provider first); the free
        #            Google endpoint runs only when the whole chain fails.
        # This whole block is what the markdown reuse above skips - it is the
        # part that spends money.
        if source_bytes is not None:
            extension = source_extension(file.filename)
            llm_client = llm_model = None
            transcribers: list = []
            if extension in IMAGE_CAPTION_EXTENSIONS:
                llm_client, llm_model = vision_llm_for(
                    project, resolver.resolve_llm_key(db, project)
                )
            elif extension in AUDIO_EXTENSIONS:
                transcribers = audio_transcribers_for(db, project)
            converted = convert_to_markdown(
                source_bytes,
                file.filename,
                llm_client=llm_client,
                llm_model=llm_model,
                transcribers=transcribers,
            )

        # The user may have deleted the file while we were converting - bail
        # before uploading markdown / paying for embeddings on a ghost.
        if not _file_still_exists(db, file.id):
            logger.info("File %s deleted during conversion - aborting", file_id)
            return

        file.page_count = converted.page_count
        file.conversion_error = None
        # e.g. "audio used the free fallback endpoint" - shown on the file row
        # and toasted by the Files tab when indexing completes.
        file.conversion_note = converted.note

        # Nothing to write back when the markdown came FROM storage - the blob
        # is already there and byte-identical, so re-uploading it is the other
        # half of the same waste.
        if cached_markdown is None:
            markdown_path = (
                file.markdown_storage_path or markdown_path_for(file.storage_path)
            )
            storage.upload_file(
                markdown_path,
                converted.markdown.encode("utf-8"),
                "text/markdown; charset=utf-8",
                upsert=True,
            )
            file.markdown_storage_path = markdown_path
            # Stamp AFTER a successful write, so a crash between the two never
            # leaves a row claiming markdown that was never stored.
            file.conversion_version = CONVERSION_VERSION
            # The text that will actually be chunked. content_sha256 pins the
            # upload and never changes; this changes whenever the conversion
            # pipeline does, which is the only trace that an edition's
            # searchable text was rewritten underneath it.
            file.markdown_sha256 = hashlib.sha256(
                converted.markdown.encode("utf-8")
            ).hexdigest()

        # -- document version gate (migration 0034) -----------------------
        #
        # Runs at most ONCE per file: only before its first successful index
        # (indexed_at is null) and only while it carries no version decision
        # (document_id is null). Both matter. Without the first, bumping
        # CONVERSION_VERSION re-converts the whole corpus and would re-examine
        # every already-confirmed file, taking a production index offline in
        # one deploy; no requeue path clears indexed_at, which is what makes it
        # a reliable "has been indexed at least once" marker. Without the
        # second, a file the user just confirmed comes back through the queue
        # and is parked again, forever - _propose_version ALWAYS returns a
        # non-null document_id, so writing it here closes the gate permanently.
        #
        # Placed AFTER the markdown upload and the conversion stamp so a park
        # commits a file whose blob is on disk and whose pipeline version is
        # recorded. The confirm then re-queues it and _reuse_converted_markdown
        # serves that blob, so conversion - which for images and audio is real
        # money on the user's own key - is never paid for twice.
        if file.document_id is None and file.indexed_at is None:
            proposal = _propose_version(db, file, project, converted.markdown)
            file.document_id = proposal.document_id  # never None - closes the gate
            file.version_label = proposal.version_label
            file.in_force_from = proposal.in_force_from
            file.legal_status = proposal.legal_status
            file.instrument_role = proposal.instrument_role
            file.relation_kind = proposal.relation_kind
            # The title the shortlist will match future uploads against. Taken
            # from the document's own first heading, so a predecessor named
            # scan_0001.pdf stops being invisible to stage one - the single
            # largest cause of a true predecessor never reaching the model.
            file.extracted_title = _extracted_title(converted.markdown)
            document_events.record_safely(
                db, project.id, "version_proposed",
                file_id=file.id, document_id=proposal.document_id,
                filename=file.filename,
                matched=proposal.document_id != file.id,
                instrument_role=proposal.instrument_role,
                version_label=proposal.version_label,
                in_force_from=proposal.in_force_from,
                refused=proposal.refused,
            )
            if proposal.document_id != file.id:
                # Suspected new edition of something already held. Stop before
                # chunking: the predecessor keeps its chunks and stays
                # searchable until a human confirms, so the corpus is never
                # briefly empty on a guess. lease_expires_at is cleared so an
                # operator reading the row is not told a dead lease is live -
                # renew_lease is scoped to status='processing' and will return
                # False on its next beat, ending the heartbeat thread.
                file.status = "review"
                file.lease_expires_at = None
                document_events.record_safely(
                    db, project.id, "parked_for_review",
                    file_id=file.id, document_id=proposal.document_id,
                    filename=file.filename,
                )
                # MUST run: the 'indexing' set at the top of this function is
                # never unwound by the normal exit below, so a project whose
                # last file parks would report 'indexing' forever.
                recompute_project_status(db, project)
                # No bump_content_version: parking changes nothing searchable,
                # so there is no cached answer to invalidate.
                db.commit()
                logger.info("File %s parked for version review", file_id)
                return
            # Committed HERE, before chunking, and not left to ride on the
            # final commit. Extraction is a paid LLM call on the user's own
            # key, and the gate that makes it exactly-once is `document_id IS
            # NULL`. If this write only landed at the end, any later failure -
            # "Document produced no chunks", a dead embedding provider - would
            # roll it back through mark_file_failed, and every retry would buy
            # the same extraction again.
            db.commit()

        # per-file overrides fall back to the project defaults
        chunk_size = file.chunk_size or project.chunk_size
        chunk_overlap = (
            file.chunk_overlap if file.chunk_overlap is not None else project.chunk_overlap
        )
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )
        chunks: list[tuple[int, int | None, str]] = []  # (chunk_index, page_number, content)
        for piece in splitter.split_text(converted.markdown):
            chunks.append((len(chunks), None, piece))
        if not chunks:
            raise ValueError("Document produced no chunks")

        api_key = resolver.resolve_embedding_key(db, project)
        # While a project is SHRUNK, embed at the width its vectors were
        # originally computed at and bank that alongside the active prefix.
        #
        # This is what removes the mixed-state problem rather than handling it:
        # without it, a file uploaded at 1536 has no 3072 numbers, so growing
        # back would leave some chunks restorable and some not - and retrieval
        # compares with <=>, which RAISES on a width mismatch, so a half-restored
        # project breaks search outright rather than degrading.
        #
        # It is free. Embedding APIs bill per TOKEN, not per dimension, so
        # asking for 3072 costs exactly what asking for 1536 costs.
        active_dims = project.embedding_dimensions
        # Via the registry, not read straight off the project: a model switch
        # can leave embedding_native_dimensions at a width the current model
        # rejects, and get_embedder RAISES on that - which would fail EVERY
        # file ingest for the project until someone shrank or grew it again.
        native_dims = registry.usable_native_dimensions(
            project.embedding_provider,
            project.embedding_model,
            project.embedding_native_dimensions,
            active_dims,
        )
        archiving = native_dims > active_dims
        embedder = get_embedder(
            project.embedding_provider,
            project.embedding_model,
            api_key,
            dimensions=native_dims,
        )

        # idempotent re-runs: drop anything from a previous attempt
        db.execute(sql_delete(Chunk).where(Chunk.file_id == file.id))
        db.commit()

        batch_size = embed_batch_size(embedder)
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            vectors = embedder.embed_texts([content for _, _, content in batch])
            rows = [
                {
                    "project_id": project.id,
                    "file_id": file.id,
                    "chunk_index": idx,
                    "page_number": page_number,
                    "content": content,
                    # Active width in `embedding` - it is what search reads, and
                    # what the partial HNSW index is built on. The wider
                    # original goes to the archive, never to `embedding`.
                    "embedding": (
                        prefix_normalize(vector, active_dims) if archiving else vector
                    ),
                }
                for (idx, page_number, content), vector in zip(batch, vectors)
            ]
            if archiving:
                # OMITTED, not set to None, when there is nothing to archive.
                # A key present in the dict makes SQLAlchemy name that column in
                # the INSERT - so carrying "embedding_full": None would reference
                # a column that does not exist until migration 0024 runs, and
                # break EVERY file upload on a database that has not had it
                # applied yet. Absent means the column is never mentioned.
                for row, vector in zip(rows, vectors):
                    row["embedding_full"] = vector
            db.execute(insert(Chunk), rows)
            db.commit()

        # Superseded WHILE this ingest ran. A claim commits immediately and
        # holds no row lock for the length of the work, so a confirm can retire
        # this file after the worker took it. _file_still_exists cannot see
        # this - a superseded row is very much still there.
        #
        # The batches already committed above are visible to search right now,
        # so leave the shape a superseded row is required to have (zero chunks,
        # chunk_count 0) rather than writing 'indexed' and putting a retired
        # version back in the index. The bump is required because those batches
        # became visible AFTER the confirm's own bump.
        if not _file_still_current(db, file.id):
            db.execute(sql_delete(Chunk).where(Chunk.file_id == file.id))
            file.chunk_count = 0
            recompute_project_status(db, project)
            bump_content_version(db, project.id)
            db.commit()
            logger.info("File %s superseded mid-ingest - chunks dropped", file_id)
            return

        file.status = "indexed"
        file.chunk_count = len(chunks)
        file.indexed_at = datetime.now(timezone.utc)
        # The moment this edition's text became answerable. Without it the
        # trail records decisions but not their effect, and cannot say what
        # was searchable on a given date.
        document_events.record_safely(
            db, project.id, "indexed",
            file_id=file.id, document_id=file.document_id,
            filename=file.filename, chunk_count=len(chunks),
            content_sha256=file.content_sha256,
        )
        recompute_project_status(db, project)
        # One atomic invalidation when the file's content becomes searchable -
        # cached answers keep serving the OLD content until this lands.
        bump_content_version(db, project.id)
        db.commit()
        logger.info("Indexed file %s (%d chunks)", file.filename, len(chunks))
    except Exception as exc:
        logger.exception("Ingestion failed for file %s", file_id)
        mark_file_failed(db, file_id, str(exc))
    finally:
        db.close()


# fail_stale_jobs is gone: restarts no longer bulk-fail in-flight work. The
# durable queue (services/ingest_queue.py) re-claims pending rows immediately
# and interrupted (leased) rows when their lease expires.
