# Audit Phase 12 — Alembic Migrations vs. ORM Models Cross-Check

**Status:** Done
**Scope:** All 47 files in `alembic/versions/`, cross-referenced against every `__tablename__` found across `app/modules/**`

**Method note:** this phase used scripted extraction (grep + a small Python parser) rather than reading every migration file individually — appropriate for a mechanical existence/consistency check across 47 files. Where the tooling had limits (see the migration-chain check below), that's stated plainly rather than papered over.

---

## Table existence cross-check (model ⇄ migration)

Extracted every table name from `op.create_table(...)` calls across all 47 migrations, and every `__tablename__` across all current models, then diffed both directions.

**Models with no backing migration (would break at runtime): zero found.** Every table any current model expects to exist has a real `create_table` migration for it — no immediate runtime-breaking gap.

**Tables that exist in migrations with no current model (orphaned at the DB level) — 5 confirmed:**

| Table | Created by | Ever dropped? | Status |
|---|---|---|---|
| `news_articles` | `cbd15ef96636_create_news_tables.py` | No `drop_table` found in any migration's `upgrade()` body | **Confirmed orphan** |
| `news_sources` | same | No | **Confirmed orphan** |
| `news_engagement` | same | No | **Confirmed orphan** |
| `news_trending` | same | No | **Confirmed orphan** |
| `user_cluster_taste` | same | No (only an FK constraint is later altered, in `d4e5f6a7b8c9_add_cascade_delete_on_user_fks.py` — never dropped) | **Confirmed orphan** |

These five all originate from the same original migration for the pre-`news_new` `app/modules/news/` package (deleted during the `54ef7e4` transition, per Phases 01/02/08's established timeline). Unlike `profile_documents` (see below), nobody ever wrote the corresponding `drop_table` when the old news module was retired. **On any database migrated forward from the beginning of this project's history, these five tables permanently exist, take up storage, and have zero application code anywhere that reads or writes them.**

**Confirmed NOT an orphan (checked specifically because Phase 03 flagged it as a question):** `profile_documents` — created in `ef6df3239d62_create_profile_module_tables.py`, and properly `op.drop_table('profile_documents')`'d in `d0e1f2a3b4c5_create_verification_module.py`'s `upgrade()` (that migration's own docstring: *"Replaces profile_documents with verification_records"*). This is exactly the cleanup the five news tables above are missing — good evidence the team knows how to do this correctly when they remember to.

**Recommended fix for the 5 orphans:** Write one new migration that drops all five tables. Low risk (nothing references them), meaningful DB hygiene win.
**Confidence:** Confirmed for all five (each independently checked for any `drop_table` call across every migration file, not just assumed from absence in a partial search).

---

## Migration chain integrity (partial verification — see caveat)

Attempted to build the full `revision` → `down_revision` graph programmatically to confirm exactly one head (current migration tip) and no broken pointers. **This was only partially automatable**: a regex-based parser correctly extracted `revision`/`down_revision` pairs for 22 of 47 files on the first pass (formatting variance across files — some use different quote/type-annotation styles Alembic's own generator produces differently across versions) — the remainder would need either a smarter parser or actually importing each module.

Rather than over-invest in perfecting that script, the specific claims it couldn't resolve were checked directly instead:
- Every `down_revision` value the partial parse reported as "pointing to a missing revision" was checked against the actual filenames (which are prefixed with their revision id) — **in every case, the target file exists.** The "missing" results were an artifact of the parser failing to extract *that* file's own `revision` line, not an actual broken chain.
- `d258688090c7_merge_heads.py` exists and has a **tuple** `down_revision = ('cbd15ef96636', 'f3a9b1c2d8e4')` — confirming the team has previously hit and correctly resolved a genuine multi-head situation (two divergent branches merged properly), which is good evidence of migration hygiene, not a problem.

**Not Proven:** a fully mechanical, 100%-parsed confirmation that there is exactly one current head today. Given (a) Alembic itself refuses to run/generate against a broken or multi-head chain without an explicit merge migration, (b) the one historical multi-head situation found was properly resolved, and (c) no dangling/missing revision target was found among the ones checked directly, this is very likely fine — but stating the limits of this check honestly rather than asserting full certainty from an admittedly partial script.

---

## Spot checks against specific claims from other phases
- `Post.title` (flagged as *missing* by `documentation/gaps.md`'s Posts Gap #1) — confirmed present in the current model (Phase 07) and backed by `33c3b84cc751_rebuild_posts_table_new_schema.py` (a full posts-table rebuild migration). Further corroborates this audit's running caution that `gaps.md` describes an old snapshot, not current state.
- `EnrichedArticle.is_government` / `commodity_tags` / `state_tags` (used throughout Phase 08's News findings) — each has its own dedicated, appropriately-named migration (`2e5f1a7c9b40_add_is_government_to_enriched.py`, `p7q8r9s0t1u2_add_commodity_state_tags_to_enriched.py`) — consistent, no drift found.
- `news_recommendation_scores` / `news_feed_ranking_cache` (Phase 08's P8-F2, the dead recommendation-engine tables) — confirmed created by `n5o6p7q8r9s0_add_news_new_tables.py`, whose own header comment lists them by name alongside the other 9 tables it adds. This closes out Phase 08's open question #17 definitively: these are real, migrated, schema-present tables that are simply never populated or read by any live code path — not a "maybe never migrated" case.

## What's solid (no action needed)
- The one genuine multi-head situation in this project's history was resolved with a proper merge migration, not by hand-editing history or dropping one branch.
- Column-level migrations for new fields (the `is_government`, `commodity_state_tags`, etc. additions) are each their own small, clearly-named migration rather than bundled into unrelated changes — good hygiene, easy to bisect if something regresses.
- No case was found of a model expecting a column/table that doesn't exist in any migration — the historically bigger risk (app crashes at a query because the DB schema hasn't caught up to the code) doesn't appear to be present anywhere in this codebase as of this audit.

## Phase 12 summary
- 1 finding: **the 5 confirmed-orphaned pre-news_new tables**, sized as Low severity (pure storage/hygiene cost, zero functional risk — nothing references them) but worth batching into the same cleanup pass as Phase 08's dead recommendation-engine tables, since both are "drop these unused tables" work of the same kind.
- No models-without-migrations found (the more dangerous direction).
- Migration chain integrity is very likely fine but not 100% mechanically proven — flagged honestly as a partial result rather than asserted with false confidence.
- Nothing found blocks moving on to Phase 13.
