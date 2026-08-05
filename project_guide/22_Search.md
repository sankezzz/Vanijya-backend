# 22 — Search

**Stated plainly, per this handbook's validation rules: there is no dedicated search module, search index, or full-text search engine anywhere in this codebase.** No Elasticsearch, no OpenSearch, no PostgreSQL full-text search (`tsvector`/`to_tsquery`), no `pg_trgm` index in any tracked migration. Every place in this app that could be described as "search" is one of two things: a plain SQL filter combined with `ILIKE` substring matching directly against Postgres, or the pgvector approximate-nearest-neighbor similarity search already covered in full in [Recommendation Engine](19_Recommendation_Engine.md) (that one is genuinely a kind of search — "find content similar to this" — just not what most people mean by the word). This chapter covers the former; if you came here looking for how the ANN "search" works, that chapter is the right one.

## Every real search-like endpoint in the app

| Endpoint | Module | What it actually does | Auth |
|---|---|---|---|
| `GET /connections/search/suggestions` | Connections | Top-8 name/business-name autocomplete | None (public) |
| `GET /connections/search` | Connections | Filtered user directory search (free text + structured filters) | Required |
| `POST /recommendations/search` | Connections | Ad-hoc pgvector similarity search with a custom payload | None (public) |
| `GET /groups/` (list/browse) | Groups | One filter among several (`search` = group name substring) | Required |

**Post and News have no search capability at all** — neither module's listing endpoints accept a free-text query parameter of any kind. Filtering a post/news feed means filtering by category, commodity, or similar structured fields already covered in [Feature Guide](10_Feature_Guide.md) — there is no way to type a word and search post captions or article text.

## Connections' search — the most fully built example

`connections/service.py`'s `search_users` (`:510-604`) is a filtered directory search against the real `profile`/`business` tables — `q` (partial name/business-name match), `role`, `commodity`, `city`, and two verification-status flags, with pagination. The one distinctive piece of logic worth knowing about is `_parse_search_intent` (`service.py:55`), which lets a single search box double as a mini structured-query parser:
```python
"""
Extracts role, commodity, city from free-text q so the frontend only needs
one search box. Explicit params passed by the caller always take priority.

"rice exporters in mumbai" -> role="exporter", commodity="rice", city="mumbai", name_q=None
"ravi broker"              -> role="broker", commodity=None, city=None, name_q="ravi"
"""
```
This only runs when the caller supplies `q` and *no* explicit `role`/`commodity`/`city` — if the client's own UI already has separate filter fields and the user filled one in, `_parse_search_intent` is skipped entirely and the explicit filters win. This means a client can offer either a single smart search box or separate structured filters, and the same backend endpoint serves both without needing to know which one a given request came from.

`search_suggestions` (`service.py:605-627`) is the simpler, public autocomplete endpoint behind the search box's live suggestions — an `ILIKE` match against `Profile.name` and (via a subquery) `Business.business_name`, capped at 8 results. **Its own docstring says "prefix suggestions"; the actual query is `ilike(f"%{q}%")` — a substring match, not a prefix match** (a leading `%` matches anywhere in the string, not just the start). This is a small, low-stakes discrepancy between what the comment claims and what the code does — in the same family as this handbook's other verified doc/code mismatches (see [Authentication](14_Authentication.md)'s token-lifetime comment, [Redis](17_Redis.md)'s stale "seen-sets" docstring) — worth knowing if you're ever debugging "why did searching 'avi' also match a business named 'Navigator Traders'."

The same docstring notes *why* `ILIKE` was chosen over something fancier: *"The old pg_trgm fuzzy match is replaced by a simpler ILIKE — same result for the common case without needing the trgm extension on the profile table."* This handbook checked every tracked migration under `alembic/versions/` for any trigram (`pg_trgm`) or `GIN` index on `profile.name` or `business.business_name`, and found none — meaning both `ILIKE '%...%'` queries run as a sequential scan today; a standard B-tree index can't serve a pattern with a leading wildcard. **Not verified from the current implementation:** whether this has caused any measured slowness at current data volume — flagged here as a factual characteristic of the query, not as a confirmed performance problem, since this handbook has no access to production query timings.

`POST /recommendations/search` (`connections/router.py:326-341`) is a different thing entirely from the two endpoints above — a direct, ad-hoc pgvector similarity query against a caller-supplied payload (commodity, quantity range, etc.), unauthenticated, intended for one-off/custom lookups rather than the personalized recommendation pipeline [Recommendation Engine](19_Recommendation_Engine.md) documents. **Not verified from the current implementation:** what client surface, if any, currently calls this endpoint — this handbook confirmed it's live and reachable (mounted via `recommendations_router` in `main.py`) but did not trace which part of the product actually uses it.

## Groups' `search` parameter

`GET /groups/` accepts `search` as one of five independent filter parameters (alongside `commodity`, `accessibility`, `region_market`, `target_role`) — a plain substring match against the group's own name, combined with whichever other filters are also supplied. There's no separate suggestions/autocomplete endpoint for groups the way Connections has one.

---
**Previous:** [21 — Image Uploads](21_Image_Uploads.md) · **Next:** [23 — Notifications](23_Notifications.md)
