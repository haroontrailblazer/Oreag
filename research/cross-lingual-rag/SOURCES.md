# Third-party material vendored in this folder

Three files here are **not** Oreag's writing. They are upstream documentation,
copied verbatim while researching language identification for the romanized-query
problem (see `12-language-routing-matrix.md`, case B).

They are kept rather than linked because the routing design depends on specific
claims in them — supported-language lists, script coverage, and reported accuracy —
and an upstream edit or deletion would silently invalidate the reasoning that cites
them. A link that rots is worse than a copy whose provenance is recorded.

**Each file retains its own upstream licence declaration, unmodified.** Nothing has
been stripped or rewritten. This table records where each came from so a reader can
tell at a glance which files are ours and which are not.

| File | What it is | Upstream | Licence, as declared in the file |
|---|---|---|---|
| `glotlid.md` | GlotLID model card | `cis-lmu/glotlid` on Hugging Face; code at `github.com/cisnlp/GlotLID` | `license: other`, `license_name: apache-2.0-plus-notices` |
| `openlid2.md` | OpenLID-v2 model card | `huggingface.co/laurievb/OpenLID`, dataset `huggingface.co/datasets/laurievb/OpenLID-v2` | **`license: gpl-3.0`** |
| `py3.txt` | py3langid README | `github.com/adbar/py3langid` | Fork BSD-3-Clause; original `langid.py` by Marco Lui, BSD-2-Clause |

## The GPL-3.0 file, stated plainly

`openlid2.md` is GPL-3.0 licensed documentation. It is included as an unmodified
verbatim copy with its licence header intact, and it is **documentation, not code** —
nothing in this repository links against, imports, derives from, or redistributes the
OpenLID model or its source. No GlotLID, OpenLID or py3langid code, weights or model
files are vendored here, and `backend/requirements.txt` depends on none of them.

If that changes — if any of these tools is ever actually adopted rather than merely
evaluated — the licence needs a real review before the dependency lands, not after.
The relevant note is in `12-language-routing-matrix.md`: the recommended detector for
romanized queries is the LLM already in the request path, precisely because it adds
no new dependency and no new licence.

Everything else in this folder is Oreag's own work.
