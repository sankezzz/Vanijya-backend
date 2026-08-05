# 28 — Common Debugging

A practical "it's broken, now what" playbook, organized by symptom. Every entry links to the chapter with the full explanation — this page is meant to get you to the right document fast, not to replace it.

## The app won't start at all

| Symptom | Likely cause | Where to look |
|---|---|---|
| Crashes immediately, before serving any request | A required environment variable is missing. Check first: `DATABASE_URL`/`SYNC_DATABASE_URL` (required `Settings` fields, no default) and `DATABASE_STORAGE_URL`/`DATABASE_SERVICE_KEY` (bracket-accessed in `shared/utils/storage.py`, crashes at import time) | [Startup Process](05_Startup_Process.md), [Configuration](24_Configuration.md) |
| Starts fine locally, fails only on a fresh clone/new machine | `.env` file is missing or incomplete locally — it's never committed | [Configuration](24_Configuration.md), [Repository Tour](03_Repository_Tour.md) |
| Starts, but one specific feature immediately 500s on first use | A `os.getenv(...)`-with-no-default value is missing (`JWT_SECRET_KEY`, `SUREPASS_TOKEN`) — this class of missing config fails softly, on first use, not at startup | [Configuration](24_Configuration.md) |

## Real-time / chat behaves inconsistently

| Symptom | Likely cause | Where to look |
|---|---|---|
| Messages arrive for some users but not others, inconsistently, especially after a redeploy or scale-up | Running more than one worker process. Every Socket.IO room membership and the chat presence dict (`_sid_user`) live in one process's memory only — a push scheduled from a different worker than the one holding the recipient's socket is silently dropped, not queued or retried | [Runtime Architecture](06_Runtime_Architecture.md), [Event Flows](20_Event_Flows.md) |
| A `new_message`/`new_group_message` event never arrives, but the message *is* in the database when you check via REST | Expected if the recipient had no open socket at that moment — there is no delivery queue for offline clients. Confirm via the REST list-messages endpoint, which is always correct regardless of the socket push | [Event Flows](20_Event_Flows.md) |
| `is_online` returns `false` for someone you're sure is connected | Check you're checking the same process — `is_online` only sees sockets connected to *this* worker | [Runtime Architecture](06_Runtime_Architecture.md), [Event Flows](20_Event_Flows.md) |

## "My scheduled job doesn't seem to run"

| Symptom | Likely cause | Where to look |
|---|---|---|
| A job "should have fired by now" per the server clock | `BackgroundScheduler` runs on `Asia/Kolkata` (IST) time, not UTC or server-local time. A `cron` job with `hour=3` fires at 3 AM IST — convert before comparing against a UTC log timestamp | [Background Jobs](18_Background_Jobs.md) |
| You want to test a job's effect right now without waiting | Four Post-module jobs and two News jobs have manual HTTP trigger endpoints that run the exact same function on demand — but two of the six require **no authentication at all**, which is itself a known gap, not a testing convenience you should rely on being there forever | [Background Jobs](18_Background_Jobs.md), [Authorization](15_Authorization.md) |
| A job silently does nothing to a specific profile/record | Check the job's own gating logic first (e.g. nightly taste promotion only touches profiles with an active Redis global-session key — a profile with zero interaction that day is legitimately skipped, not broken) | [Recommendation Engine](19_Recommendation_Engine.md) |

## "Recommendations / rankings look wrong"

| Symptom | Likely cause | Where to look |
|---|---|---|
| A brand new profile with declared commodities/role sees generic-feeling results | Expected — the dynamic taste system needs real interaction history to produce a boost; a cold-start profile gets pure persistent (often empty) weights. This isn't a bug, it's the intended cold-start behavior | [Recommendation Engine](19_Recommendation_Engine.md) |
| Group suggestions never seem to reward genuinely active groups over quiet ones | Confirmed, real gap: `GroupActivityCache` is written once at zero and never refreshed by anything — the activity half of the ranking formula is always exactly `0.0` in the currently-running code | [Caching](16_Caching.md), [Recommendation Engine](19_Recommendation_Engine.md) |
| A taste-boosted score doesn't seem to change even after several relevant actions | Check for a Redis connectivity problem first — every taste read/write is wrapped in a silent `try/except: pass`, so a Redis outage degrades to "no boost" without any visible error anywhere | [Recommendation Engine](19_Recommendation_Engine.md), [Redis](17_Redis.md) |
| A post marked "followers only" or role-targeted is visible to someone who shouldn't see it | Confirmed, real gap (audit P11-F1) — visibility filtering is only enforced in one of several post-serving code paths | [Authorization](15_Authorization.md) |

## "I got a 404/403/422 and I'm not sure why"

| Symptom | Likely cause | Where to look |
|---|---|---|
| A 404 on a resource you're fairly sure exists | Some ownership checks are baked directly into the query's `WHERE` clause (e.g. Connections' `respond_to_request`) rather than fetch-then-compare — "exists but isn't yours" and "doesn't exist" both come back as the same 404 in those specific endpoints | [Authorization](15_Authorization.md) |
| A 422 with a single plain-string `detail` | A hand-raised business-rule failure from a module's own service layer (Layer 2) | [Error Handling](25_Error_Handling.md) |
| A 422 with a structured, per-field `detail` list | FastAPI's automatic Pydantic validation (Layer 1) — the request body/params didn't match the schema's shape, before any of your endpoint's own code ran | [Error Handling](25_Error_Handling.md), [Request Lifecycle](07_Request_Lifecycle.md) |
| A bare 500 with no useful detail in the response | An exception nothing caught — check Sentry first (it auto-captures this even though the client sees nothing informative), then trace which module's router is missing a translation for whichever exception type was raised | [Error Handling](25_Error_Handling.md) |

## "Search isn't finding what I expect"

| Symptom | Likely cause | Where to look |
|---|---|---|
| A search matches something you didn't expect it to (e.g. matches partway through a word) | `search_suggestions`'s docstring says "prefix" but the actual query is a substring `ILIKE '%q%'` — this is a real, confirmed doc/code mismatch, not a bug in your test | [Search](22_Search.md) |
| Typing a phrase like "rice exporters in mumbai" into Connections' search unexpectedly filters by role/commodity/city | Working as designed — `_parse_search_intent` extracts structured filters from free text automatically, but only when you haven't already supplied those filters explicitly | [Search](22_Search.md) |
| Post or News listings don't support any text search at all | Confirmed — neither module has a search parameter of any kind; this isn't a missing feature you're failing to find, it genuinely doesn't exist yet | [Search](22_Search.md) |

## "The test suite won't run"

Confirmed, existing, unresolved as of this handbook: `pytest` isn't declared in `requirements.txt`, and the prior audit found `tests/conftest.py` patches a symbol that no longer exists in `main.py` after the News module's rewrite (audit P1-F2, Critical). Don't spend time assuming your own environment is misconfigured before checking this — see [Known Limitations](30_Known_Limitations.md) and [Deployment](26_Deployment.md).

## "Sentry isn't tagging my new module's requests correctly"

`core/monitoring.py`'s `install_module_tag_middleware` tags each request's Sentry transaction with an owning module name, based on a hardcoded URL-prefix-to-module-name table (`_MODULE_PREFIXES`). The prior audit found this table already silently stale for two modules whose URL prefixes changed since the table was written (`/post` should be `/posts`, `/deeplink` should be `/share` — audit P1-F3). If Sentry traces for a module look like they're landing under the wrong tag (or no tag), check this table before assuming Sentry itself is misconfigured.

---
**Previous:** [27 — Glossary](27_Glossary.md) · **Next:** [29 — FAQs](29_FAQs.md)
