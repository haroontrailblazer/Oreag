"""The index config and the query config must never drift apart.

`content_tsv` is what gets INDEXED; `websearch_to_tsquery` is what gets
SEARCHED. If one says 'english' and the other says 'simple', the terms never
meet and lexical search returns nothing at all - no error, no warning, just an
empty half of hybrid search that looks exactly like "this corpus had no keyword
matches". Nothing else in the suite would catch it, because the suite runs on
SQLite where neither expression exists.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
RETRIEVAL = pathlib.Path(__file__).resolve().parent.parent / "app/services/retrieval.py"


def _query_configs() -> set[str]:
    src = RETRIEVAL.read_text(encoding="utf-8")
    return set(re.findall(r"websearch_to_tsquery\('(\w+)'", src))


def _index_config() -> str:
    """The config on the LATEST migration that defines content_tsv."""
    migrations = sorted((ROOT / "supabase/migrations").glob("*.sql"))
    latest = None
    for path in migrations:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"generated always as \(to_tsvector\('(\w+)'", text
        ):
            latest = match.group(1)
    assert latest, "no migration defines content_tsv"
    return latest


class TestConfigsAgree:
    def test_every_query_uses_one_config(self):
        configs = _query_configs()
        assert len(configs) == 1, f"retrieval.py mixes configs: {configs}"

    def test_the_query_matches_the_index(self):
        query = _query_configs().pop()
        assert query == _index_config(), (
            f"lexical search queries with '{query}' but content_tsv is built "
            f"with '{_index_config()}' - the terms will never meet and lexical "
            "search will silently return nothing"
        )

    def test_it_is_a_stemming_config(self):
        """'simple' does not stem, so "investing" never reached "invest" and
        the lexical half was close to dead weight on prose."""
        assert _index_config() != "simple"
