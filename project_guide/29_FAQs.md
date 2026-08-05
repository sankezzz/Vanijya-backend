# 29 — FAQs

Questions a new engineer would plausibly ask in their first weeks, answered directly, with links to the full explanation.

**Why are there four folders that all sound like documentation — `documentation/`, `upgraded_documentation/`, `audit/`, `audits/`?**
`documentation/` and `upgraded_documentation/` are pre-existing docs written before this handbook, and both were found to drift from the current code in places — spot-check anything from either against the actual source before trusting it. `audit/` is a 14-phase, evidence-based production-readiness audit (54 findings, all cited throughout this handbook as `P#-F#`). `audits/` — this handbook — is what you're reading now: written afterward, verified independently against current code, and explicitly not a repeat of the audit's critical framing. See [Repository Tour](03_Repository_Tour.md).

**Why do `chat/` and `taste/` look structurally different from every other module?**
They use a layered (`domain/`/`application/`/`data/`/`presentation/`) architecture; every other module is flat (`router.py`/`service.py`/`models.py`). Both styles are valid; this app just doesn't use one consistently. Copy whichever style matches the module you're editing, not whichever you personally prefer. See [Modules](11_Modules.md).

**Isn't `global_session` and `global_taste` the same thing? Why are there two packages with almost the same name?**
No — genuinely two different things, and the near-identical names are a real, acknowledged trap. `global_session` is Redis-backed, one-day TTL. `global_taste` is Postgres-backed, permanent. See [Redis](17_Redis.md)'s explicit map of the three taste packages before you trust an import statement you're skimming.

**Can I delete `news_recommendation_engine/`? The audit says it's dead.**
Not the whole folder. Its `service.py`, `router.py`, and two database tables genuinely have zero live callers (audit P8-F2) — but `profile_scorer.py`, one file in that same package, is imported directly by the live News feed and is very much not dead. This handbook's own earlier drafts got this wrong at first and were corrected once verified against current code — see [Recommendation Engine](19_Recommendation_Engine.md) for the full story. Check actual import statements before deleting anything, regardless of what a folder name or a prior finding implies about the folder as a whole.

**Can I delete `app/config.py`?**
As far as this handbook could verify, yes — nothing imports it anywhere. It's a second, unrelated `Settings` class that happens to share a name with the real one in `app/core/config.py`. Confirm with whoever owns deploy/CI decisions before removing any file outright, per this handbook's own caution about acting on audit findings without a final check. See [Configuration](24_Configuration.md).

**Why does `profile/` depend on `connections/`, and `connections/` also depend on `profile/`? Isn't that circular?**
It would be, as a module-level import — which is exactly why it's avoided: some cross-dependencies are written as function-local imports (inside a function body, not at the top of the file), specifically to break the cycle at import time while still letting the function call what it needs at runtime. `connections/service.py`'s `_activate_dm` importing from `chat` this way is the clearest example. See [Modules](11_Modules.md).

**I need to add an admin-only endpoint. How do I gate it?**
Honestly: this app has no admin/role-checking mechanism to reach for yet. Don't use the `Role` table (Trader/Broker/Exporter — a business classification, not a permission level) and don't ship it ungated "temporarily" — two endpoints already in production did exactly that, are known gaps (audit P8-F1, P13-F1), and neither has been fixed as of this handbook. Treat "we need an admin concept" as a decision to raise, not a pattern to copy. See [Authorization](15_Authorization.md).

**Can I add `--workers 4` to the Uvicorn start command to handle more load?**
Not without also doing the migration work first. This app's real-time layer (Socket.IO room membership, the chat presence dict) lives in one process's memory; a second worker would have its own separate, unsynchronized copy, and messages would start silently failing to reach some recipients. The fix (`socketio.AsyncRedisManager` + moving presence state into Redis) is named directly in `connection_manager.py`'s own docstring but hasn't been done. See [Runtime Architecture](06_Runtime_Architecture.md) and [Event Flows](20_Event_Flows.md).

**How do I know if a piece of code I'm reading is actually used, versus a leftover from an earlier version?**
Grep for its actual import statements or call sites — don't infer liveness from which folder it's in, what its docstring claims, or what a prior audit said about the module as a whole. This exact mistake (assuming an entire folder was dead because most of it was) is what produced this handbook's own `news_recommendation_engine` correction above. See [Modules](11_Modules.md) for the verified live dependency graph as it stood when this was written — "as it stood" being the operative caveat.

**Where should a brand-new feature's code live — a flat module or a layered one?**
Flat, by default — it's what almost everything in this app already does, and it's simpler for a small-to-medium feature. Reach for the layered style only if the feature genuinely has the same shape that justified it for `chat`/`taste`: multiple real, swappable data sources, or business logic complex enough to want dedicated use-case classes. See [Repository Tour](03_Repository_Tour.md) and [Repositories](13_Repositories.md).

**How do I add a new environment-variable-backed configuration value?**
Add a typed field to the real `Settings` class in `app/core/config.py` and import `settings` where you need it — don't add another scattered `os.getenv(...)` call. This app already has nine-plus of those bypassing `Settings`, and one config value (`GOOGLE_SERVICE_ACCOUNT_JSON`) is read both ways in two different files as a direct consequence. See [Configuration](24_Configuration.md).

**What do the `P1-F1`, `P8-F2`-style codes mean when this handbook cites them?**
They're finding IDs from the prior architectural audit — `P<phase number>-F<finding number>`, e.g. `P8-F2` is the second finding written up in that audit's Phase 8. The full evidence, exact file/line references, and recommended fix for any of them live in `audit/audit_phase_0N.md`; this handbook cites the ID and a short description rather than re-deriving the full writeup. See [Known Limitations](30_Known_Limitations.md) for the consolidated list.

**The taste/recommendation system seems really deep. Do I need to understand all of [Recommendation Engine](19_Recommendation_Engine.md) just to fix a bug in, say, Groups?**
No. If your change doesn't touch personalization/ranking, you can safely skip it — [Modules](11_Modules.md) and [Feature Guide](10_Feature_Guide.md) cover what most day-to-day feature work actually needs. Come back to [Recommendation Engine](19_Recommendation_Engine.md) specifically when you're touching ranking, taste signals, or anything Redis-backed under `taste/`.

**Can I trust everything in this handbook to still be accurate by the time I'm reading it?**
Treat it the way this handbook treats the prior audit and `documentation/`: as a well-verified snapshot, not an eternal truth. This handbook itself documents a real case — the taste system's city/state generalization — where the code changed between the prior audit and this handbook being written, and this handbook had to independently re-verify and correct its own draft accordingly. If something you're reading here doesn't match the code in front of you, the code wins; consider updating this handbook alongside your change.

---
**Previous:** [28 — Common Debugging](28_Common_Debugging.md) · **Next:** [30 — Known Limitations](30_Known_Limitations.md)
