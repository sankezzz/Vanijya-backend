# Codebase Knowledge Book - Progress Tracker

**Continuation protocol:** starting a new chat? Say "continue the knowledge book from `audits/PROGRESS.md`". Read this file, then the most recently completed doc, then continue with the next Pending file below.

## What this is

A 32-file internal engineering handbook for the Vanijyaa backend, written for a new engineer with zero prior context - not another audit. The prior architectural audit (`audit/audit_phase_01.md` through `audit_phase_14_FINAL_REPORT.md`) is used as supporting cross-reference where relevant (dead code, known gaps), but the source of truth for every claim in this handbook is the current codebase, verified by direct reading - not inherited from the audit or from `documentation/` / `upgraded_documentation/` (both pre-existing doc sets found to drift from current code during the audit; same caution applies here).

## Ground rules

- Every factual claim traces to: implementation, migration, config, or a clearly-marked audit finding. Anything that can't be verified is stated as "Not verified from the current implementation" - not guessed.
- Concepts (FastAPI, SQLAlchemy, Redis, dependency injection, repository pattern, etc.) are introduced before they're used - assume zero prior framework knowledge.
- Diagrams (Mermaid) wherever they clarify better than prose - flowcharts for pipelines, sequence diagrams for request/response, ER diagrams for data model, state diagrams for lifecycle.
- Cross-link between docs liberally using relative links, e.g. `[Authentication](14_Authentication.md)`.
- Code references use the form `path/to/file.py` with function/class name, and a line number when practical.

## File status

| # | File | Covers | Status |
|---|---|---|---|
| - | PROGRESS.md (this file) | Tracker + ground rules | Done |
| 00 | Project_Introduction.md | What Vanijyaa is, who it's for, why this doc set exists | Done |
| 01 | Product_Overview.md | The product from a user's perspective - every feature area in plain language | Done |
| 02 | How_the_System_Works.md | The 10,000-ft technical mental model - one diagram, one story | Done |
| 03 | Repository_Tour.md | Guided walkthrough of the repo, folder by folder, why each exists | Done |
| 04 | Folder_Structure.md | Reference-style folder tree with one-line purpose per directory | Done |
| 05 | Startup_Process.md | What happens from `uvicorn main:app` to "ready to serve" | Done |
| 06 | Runtime_Architecture.md | Processes, threads, connections: what's running at any moment | Done |
| 07 | Request_Lifecycle.md | One HTTP request, start to finish, every layer | Done |
| 08 | API_Flows.md | Concrete request/response walkthroughs for representative endpoints | Done |
| 09 | Database_Guide.md | Every table, every relationship, ER diagrams, migration story | Done |
| 10 | Feature_Guide.md | Every user-facing feature, end-to-end | Done |
| 11 | Modules.md | Every app/modules package: purpose, interface, dependents | Done |
| 12 | Service_Layer.md | The service-layer pattern as used here | Done |
| 13 | Repositories.md | Repository pattern usage (real in Chat/Taste, absent elsewhere) | Done |
| 14 | Authentication.md | Firebase phone OTP to JWT, end to end | Done |
| 15 | Authorization.md | Who can do what - ownership checks, admin gaps, audit cross-refs | Done |
| 16 | Caching.md | What's cached, where, TTLs, invalidation | Done |
| 17 | Redis.md | Every Redis key namespace in the app, explained | Done |
| 18 | Background_Jobs.md | APScheduler jobs - what runs, when, why | Done |
| 19 | Recommendation_Engine.md | Deep dive: taste system + per-module recommenders | Done |
| 20 | Event_Flows.md | Real-time events (Socket.IO) + "event-like" fan-outs | Done |
| 21 | Image_Uploads.md | Signed-URL upload pattern, used by 4 modules | Done |
| 22 | Search.md | Search-as-filter-parameter (no dedicated search module - stated plainly) | Done |
| 23 | Notifications.md | FCM token plumbing exists; no send pipeline found - stated plainly | Done |
| 24 | Configuration.md | Settings, env vars, the 3-strategy inconsistency (cross-ref audit) | Done |
| 25 | Error_Handling.md | Exception hierarchy per module to HTTP status mapping | Done |
| 26 | Deployment.md | Render.com deploy, what's in render.yaml, what's manual | Done |
| 27 | Glossary.md | Every domain + technical term used across the book | Done |
| 28 | Common_Debugging.md | "It's broken, now what" - practical triage playbook | Done |
| 29 | FAQs.md | Anticipated new-engineer questions | Done |
| 30 | Known_Limitations.md | Honest list, audit cross-referenced | Done |
| 31 | Architecture_Decisions.md | ADR-style record of the big "why" decisions, reconstructed from evidence | Done |

## Source material used

- `audit/audit_phase_01.md` through `audit_phase_14_FINAL_REPORT.md` - prior architectural audit, used as cross-reference and marked wherever cited.
- Direct reading of `app/**`, `alembic/versions/**`, `main.py`, `requirements.txt`, `render.yaml`, `.env` (structure only, no secret values reproduced).
- `documentation/*.md` and `upgraded_documentation/*.md` - pre-existing docs, spot-checked, not trusted blindly (the audit found both sets drift from current code in places).
