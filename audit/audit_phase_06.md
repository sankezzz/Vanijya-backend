# Audit Phase 06 — Chat Module

**Status:** Done
**Scope:** `app/modules/chat/**` — `presentation/{router,connection_manager,dependencies,schema}.py`, `service.py`, `domain/{entities,use_cases}.py`, `data/{models,repository}.py`

**This phase surfaced the most significant finding of the audit so far — read P6-F1 first.**

---

## Files inspected

| File | Purpose | Verdict |
|---|---|---|
| `presentation/router.py` | 15 REST endpoints under `/chat` | Live, fully JWT-gated. See P6-F2, P6-F5 |
| `presentation/connection_manager.py` | Socket.IO server + real-time emit helpers | Live. Self-documents a single-worker constraint. See P6-F6 |
| `presentation/dependencies.py` | FastAPI DI wiring for 11 use cases | Live. Wildcard import — see P6-F5 |
| `presentation/schema.py` | Request/response Pydantic models | Live. See P6-F3 |
| `service.py` | Chat media upload/delete (Supabase) | Live, clean, mirrors post/profile/groups storage pattern correctly |
| `domain/entities.py` | Pure dataclasses — conversation/message/snap shapes | Live. `ConvStatus.BLOCKED` defined here — see P6-F1 |
| `domain/use_cases.py` | Business rules per action | Live. **Contains the commented-out block check — P6-F1** |
| `data/models.py` | `Conversation`, `ConversationMember`, `Message`, `ChatAttachment` | Live, correct schema |
| `data/repository.py` | All DB access — `ChatRepository` | Live, well-batched (no N+1 patterns found — see "What's solid"). Contains the duplicate DM-creation logic — see P6-F2 |

---

## Reconciliation with `documentation/BACKEND_AUDIT.md` (Chat's bug: BUG-004) and Phase 01's open question #7

**Resolved:** the prior audit's BUG-004 cited a file (`ws_router.py`) that no longer exists. What actually happened: the raw FastAPI WebSocket approach BUG-004 was written against was replaced entirely by a Socket.IO server (`connection_manager.py`, mounted in `main.py` via `socketio.ASGIApp(sio, other_asgi_app=app)`). The **authentication** half of BUG-004 is **fixed**: every REST endpoint requires `Depends(get_current_user_id)`, and the Socket.IO `connect` handler (`connection_manager.py:30-39`) validates the JWT via `decode_access_token(token)` and refuses the connection (`return False`) on failure — no anonymous or impersonated socket connections are possible.

However, this phase found a **different, more severe authorization gap in the same area** — not "who are you" (fixed) but "are you allowed to do this to this specific conversation" (not fixed). See P6-F1. Don't conflate the two; BUG-004 as originally written is closed, but Chat is not clean.

---

## Findings

### P6-F1 — Blocking a user provides zero real protection: the block check is commented out, and nothing ever sets a conversation's status to "blocked" in the first place
**Severity:** Critical
**Category:** Correctness / Missing Connection / Trust & Safety
**Files:** `app/modules/chat/domain/use_cases.py:57-87` (`SendMessageUseCase`), `app/modules/safety/service.py` (whole file), `app/modules/chat/data/repository.py:856-885` (`get_or_create_dm`)

**Reason — three independent, compounding failures, each verified directly:**

1. **The enforcement code is disabled.** `SendMessageUseCase.execute()`:
   ```python
   guard = self.repo.get_conv_send_info(conv_id, sender_id)
   if not guard:
       raise HTTPException(status_code=404, detail="Conversation not found.")
   # if guard.status == ConvStatus.BLOCKED:
   #     raise HTTPException(status_code=403, detail="Blocked conversation.")
   ```
   The comment immediately above the class (`use_cases.py:51-55`) documents the *intended* rule — `BLOCKED → nobody can send → 403` — but the `if` that would enforce it is commented out. Every DM send goes straight through regardless of conversation status.

2. **Even if re-enabled, it would never fire.** Grepped every reference to `"blocked"` / `ConvStatus.BLOCKED` in the codebase — four total: the enum definition (`entities.py:15`), the disabled check itself, the comment describing it, and one read in `connections/service.py:454` (`_activate_dm`, which raises 403 if it happens to find an existing conversation already in `BLOCKED` status). **Nothing anywhere sets a `Conversation`'s status to `"blocked"`.** Read `app/modules/safety/service.py` in full: `block_user()` only inserts a row into the separate `UserBlock` table — it has zero interaction with `Conversation` at all.

3. **The safety module's own designed integration points are completely unused.** `safety/service.py` defines `is_blocked()` and `either_blocked()` specifically so other modules can gate DMs/feeds with them — its own docstring says so (`"Useful for DM / feed guards"`), and this is echoed in `documentation/security.md` (the Safety API docs): *"Block — hides the blocked user from the blocker's feeds, DMs, and recommendations."* Grepped every call site of `is_blocked`/`either_blocked` across the entire `app/` tree: **the only matches are their own definitions.** Zero callers, anywhere — not in chat, not in connections, not in feed, not in post.

**Net effect:** blocking another user (`POST /safety/{user_id}/block/{target_id}`) does not stop them from continuing to send DM messages. This directly contradicts the shipped documentation's explicit promise. On a platform for business/trade contacts where blocking is presumably the primary recourse against harassment or spam, this is a real, user-facing safety gap, not a cosmetic one.

**Recommended fix (three-part, matching the three failures above):**
1. Un-comment the `BLOCKED` check in `SendMessageUseCase` (and consider the same for `CreatePersonalDealUseCase`'s parallel disabled check, P6-F4).
2. Decide where "blocked" status actually belongs: either (a) have `safety.block_user()` also set `Conversation.status = ConvStatus.BLOCKED` for any existing DM between the two users, or (b) — likely the better fit given `either_blocked()` already exists for exactly this — have `get_conv_send_info`/`SendMessageUseCase` call `safety.service.either_blocked(db, sender_id, receiver_id)` directly instead of relying on a `Conversation.status` field that nothing else maintains. Option (b) avoids needing to keep two separate systems (`UserBlock` rows and `Conversation.status`) in sync.
3. Apply the same `either_blocked()` check to conversation creation (`get_or_create_dm`) too, not just message sending — right now a blocked user could still successfully call `POST /chat/conversations` and get a conversation ID back, only failing (once fixed) on the first actual message.

**Risk:** Low to fix, but test carefully — this is exactly the kind of change where a partial fix (e.g., only gating new conversations but not existing ones, or only gating one of the two message-send use cases) leaves a false sense of security.
**Cleanup effort:** Small–Medium (~2-3 hrs incl. picking the integration approach and testing both directions of block).
**Confidence:** Confirmed at every step — this was not left as a hunch; each of the three failure points was independently grepped and read in full before concluding.

---

### P6-F2 — Two independent, behaviorally-different implementations of "find or create a DM conversation" — the newer one bypasses the message-request consent gate entirely
**Severity:** High
**Category:** Duplicate Logic / Architecture
**Files:** `app/modules/chat/data/repository.py:856-885` (`get_or_create_dm`) vs. `app/modules/connections/service.py:423-459` (`_activate_dm`, read in Phase 04)

**Reason:** Both functions solve the same problem — get or create the DM `Conversation` between two users — with different rules:
- `_activate_dm` (Connections module) is only reachable via `MessageRequest` accept (`respond_to_request`) — i.e., only after the receiver has explicitly consented. It also refuses to reactivate a `BLOCKED` conversation (403).
- `get_or_create_dm` (Chat module) is reachable directly via `POST /chat/conversations` with just a `participant_id` in the body — **no `MessageRequest` involved at all**, and no `BLOCKED` check (see P6-F1).

Since `data/models.py`'s own comment on `Conversation.status` reads `# was "requested" — message request gate bypassed`, this looks like a **deliberate** past decision to let DMs start immediately rather than requiring the request/accept round-trip — but if so, it directly contradicts the `MessageRequest` system's entire reason for existing (Connections module: send/withdraw/accept/decline, `first_message` seeding, notifications on accept/decline). Anyone can skip straight past all of that by calling `POST /chat/conversations` instead of `POST /connections/message-request/{target_id}`.

This exact tension is already flagged, without this level of code detail, in `documentation/gaps.md`'s Chat Gap #1: *"Two conflicting chat request systems... Decision required: either wire MessageRequest acceptance to create a Conversation, or deprecate MessageRequest and use only the Conversation request flow."* This phase confirms which one actually won in the code (Conversation, born active, no gate) — but nobody deprecated the other one, so both remain live and inconsistent.

**Recommended fix:** This is a product decision, not just a refactor (flagging for the user, not picking a side):
- **Option A** — Formally retire the consent-gate idea: keep `POST /chat/conversations` as the only way to start a DM, and demote `MessageRequest` to what it's still useful for (the `first_message`/intro-line UX), or remove it if that's also not needed.
- **Option B** — Actually enforce consent: make `get_or_create_dm` create conversations in a genuinely gated state (or refuse entirely) unless a `MessageRequest` between the two users has been accepted, unifying the two code paths into one.
Either way, `get_or_create_dm` and `_activate_dm` should end up as one function, not two independently-maintained ones that already disagree on the `BLOCKED` case.
**Risk:** Medium — this is user-facing behavior change either direction; needs a product decision before it's a pure code task.
**Cleanup effort:** Medium (~half a day once the direction is decided, including frontend coordination if the flow visibly changes).
**Confidence:** Confirmed (both full functions read, in this phase and Phase 04 respectively; the model comment is read verbatim).

---

### P6-F3 — News-article sharing into chat has a fully-built read path and no write path at all
**Severity:** Low
**Category:** Missing Connection / Incomplete Feature
**Files:** `app/modules/chat/data/models.py:79-81` (`Message.article_id`), `data/repository.py:181-195,315-322,363-373` (news-article snap builders), `presentation/schema.py:13-23` (`SendMessageRequest`), `domain/use_cases.py:57-87` (`SendMessageUseCase.execute`)

**Reason:** The read/render side is fully built: `Message.article_id` is a real FK column (with its own migration, `o6p7q8r9s0t1_add_article_id_to_messages.py`), `_news_article_snap`/`_news_article_snaps_bulk` correctly join to `news_new`'s `RawArticle`/`EnrichedArticle` and populate `MessageEntity.news_article`. But there is no way for a client to ever create such a message: `SendMessageRequest`'s `message_type` field is a regex-constrained string (`text|image|video|document|audio|location|deal|post`) that **does not include `"news"`**, the schema has no `article_id` field at all, and `SendMessageUseCase.execute()`'s parameter list has no `article_id` either — even though `ChatRepository.save_message()` one level down already accepts `article_id: Optional[UUID] = None` and would happily persist it if anything ever passed one in.
**Recommended fix:** Either finish the write path (add `article_id` to `SendMessageRequest`/`SendGroupMessageRequest`, thread it through both use cases, add `"news"` to the `message_type` pattern) if news-sharing-to-chat is still wanted, or remove the now-orphaned read-side plumbing if the feature was abandoned. Flagging as a decision point — Not Proven which the product actually wants.
**Risk:** None to assess further without a product answer.
**Cleanup effort:** Small (~1 hr) to complete the write path if that's the direction chosen.
**Confidence:** Confirmed (schema, use case signatures, and repository signature all read directly).

---

### P6-F4 — A second disabled status check, same anti-pattern as P6-F1, lower impact
**Severity:** Low
**Category:** Correctness
**Files:** `app/modules/chat/domain/use_cases.py:147-157` (`CreatePersonalDealUseCase`)

**Reason:**
```python
conv = self.repo.get_conversation(conv_id, sender_id)
if not conv:
    raise HTTPException(status_code=404, detail="Conversation not found.")
# if conv.status != ConvStatus.ACTIVE:
#     raise HTTPException(status_code=403, detail="Can only create deals in an active conversation.")
```
Lower impact than P6-F1 because — per P6-F1's finding #2 — conversation status is essentially always `"active"` in practice (nothing sets any other value), so this guard would rarely have anything to reject even if enabled. Still the same pattern: a safety check was written, then disabled, then left in the codebase indefinitely rather than either fixed or deleted.
**Recommended fix:** Resolve alongside P6-F1/P6-F2 once the conversation-status model is settled — don't fix in isolation, since its correctness depends on what `ConvStatus` actually gets used for after that decision.
**Risk:** None (currently near-unreachable given no status is ever anything but active).
**Cleanup effort:** Trivial once P6-F1/F2 are resolved.
**Confidence:** Confirmed (read directly).

---

### P6-F5 — Wildcard import (minor style inconsistency)
**Severity:** Nice to Have
**Category:** Maintainability
**Files:** `app/modules/chat/presentation/dependencies.py:4`

**Reason:** `from app.modules.chat.domain.use_cases import *` — every other file read in this entire audit so far uses explicit named imports; this is the only wildcard import found. Low practical risk given the module is small and self-contained, but inconsistent with the rest of the codebase and makes it harder to see at a glance what a file actually depends on.
**Recommended fix:** Replace with explicit imports of the 11 use-case classes actually used.
**Risk:** None.
**Cleanup effort:** Trivial (~5 min).
**Confidence:** Confirmed.

---

### P6-F6 — Real-time layer is explicitly single-worker-only (self-documented; not currently triggered, but a real landmine)
**Severity:** Medium
**Category:** Architecture / Scaling risk
**Files:** `app/modules/chat/presentation/connection_manager.py:1-15`

**Reason:** The module's own docstring is unusually candid and accurate: `_sid_user` is an in-process dict and Socket.IO uses its default in-memory client manager, so `emit_to_user`/`is_online`/room membership only see sockets connected to the *same* worker process that's handling a given HTTP request. Cross-worker pushes are silently dropped — no error, just a message that never arrives in real time (it would still be persisted to the DB and show up on next poll/refresh, so this is a real-time-delivery gap, not a data-loss one).

**Current risk level:** Low today — `render.yaml`'s `startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT` has no `--workers` flag, so it runs uvicorn's default single worker. This is not an active bug in the current deploy config.
**Why it's still worth tracking:** it's exactly the kind of setting someone "helpfully" changes later (e.g., adding `--workers 4` for perceived performance under load) without knowing this file depends on staying single-worker — and when that happens, the failure mode is silent (some users just stop getting real-time pushes, intermittently, based on which worker they landed on), which is a nasty thing to debug blind.
**Recommended fix:** Not urgent to change the architecture now, but worth either a comment in `render.yaml` itself pointing back at this constraint, or (properly) migrating to `socketio.AsyncRedisManager` + Redis-backed `_sid_user` before ever scaling past one worker — the module's own docstring already says exactly this.
**Risk:** None to flag; risk is in *not* flagging it before someone changes the deploy config.
**Cleanup effort:** Just documentation/deploy-config cross-reference now; Medium effort (~1 day) if/when the Redis-backed version is actually needed.
**Confidence:** Confirmed (docstring + `render.yaml` both read directly).

---

### P6-F7 — Group deal *creation* lives only in the Chat router, breaking the resource-ownership convention every other Group-deal operation follows
**Severity:** Medium
**Category:** Architecture / Responsibility Boundary
**Files:** `app/modules/chat/presentation/router.py:297-310` (`create_group_deal_endpoint`, `POST /chat/groups/{group_id}/deals`) vs. `app/modules/groups/router.py:522-580` (`GET /deals`, `GET /deals/{deal_id}`, `PATCH /deals/{deal_id}`, `POST /deals/{deal_id}/close`, `POST /deals/{deal_id}/publish` — all under `/api/v1/groups/{group_id}/...`)

**Reason:** `GroupDeal` is a Groups-module model (`app/modules/groups/models.py`), and every operation on it *except creation* is exposed under the Groups router's own `/api/v1/groups/{group_id}/deals/...` namespace. Deal **creation** (`create_group_deal`, defined in `groups/service.py`) is instead only reachable via the Chat router's `POST /chat/groups/{group_id}/deals` — there is no `POST /api/v1/groups/{group_id}/deals` at all. This means a client building "view/edit a group's deals" functionality has to know that one specific operation on that same resource lives under a completely different URL prefix, owned by a different module. The likely reason (deal creation also drops a system message card into group chat, `_insert_deal_chat_card`) is reasonable, but doesn't require the *entire* creation endpoint to live in Chat's router — the router could stay in Groups and still call into chat internals, the same way several other cross-module calls in this codebase already do (e.g. Connections' router already imports `chat.presentation.connection_manager.emit_to_user` directly).
**Recommended fix:** Add `POST /api/v1/groups/{group_id}/deals` to `groups/router.py` calling the same `create_group_deal` service function (which already lives in `groups/service.py`), and either keep `POST /chat/groups/{group_id}/deals` as a thin alias for backward compatibility or remove it once clients are confirmed off it.
**Risk:** Low — additive if kept as an alias; needs a frontend-usage check before removing the Chat-router path outright (**Not Proven** whether the frontend already depends on the current path).
**Cleanup effort:** Small (~30–45 min for the additive fix).
**Confidence:** Confirmed (both routers read in full; `create_group_deal` traced to its single current call site).

---

## What's solid (no action needed)
- `ChatRepository`'s batch-builder functions (`_build_conversations`, `_build_messages`, `_group_last_messages_bulk`) are genuinely well-built — each explicitly avoids the N+1 pattern flagged repeatedly elsewhere in this audit (BUG-013/014/015), with code comments calling out exactly what per-row query they're replacing. This module has the best query-batching discipline of any module audited so far.
- `soft_delete_message` correctly verifies ownership (`msg.sender_id != user_id` → refuse) before flipping `is_deleted`, and separately collects storage paths for best-effort cleanup — no ownership gap here (contrast with P6-F1's very different, real gap).
- `get_share_recipients`'s single unified DM+group list with a coherent null-sinks-to-bottom sort is a clean, well-thought-out piece of response shaping, not duplicated elsewhere.
- Group-chat send rules (`SendGroupMessageUseCase`) correctly check membership, frozen status, and admin-only posting permission, in the right order, with clear 403 messages — no gaps found here, a useful contrast showing the team knows how to write this kind of guard correctly (making P6-F1's disabled guard look more like a regression than a knowledge gap).

## Unresolved questions handed to later phases
- Open question #11 (`is_deleted` in chat) is **resolved, not carried forward**: `Message.is_deleted` is a real, consistently-used soft-delete flag (default `False`, flipped by `soft_delete_message`); Connections' `_seed_first_message` (Phase 04) sets it to `False` explicitly at creation, matching the default — no inconsistency found.
- **[Phase 07/09]** P6-F1's "zero callers for `is_blocked`/`either_blocked`" claim is as of Chat + everything audited through Phase 06. Post and Feed modules (not yet audited) are exactly where a block-check would also be expected (feeds/recommendations) per Safety's own doc claim ("hides... from feeds and recommendations" too, not just DMs) — Phases 07 and 09 must check specifically, not assume this phase already covered them.
- **[Phase 11]** P6-F1's fix needs a decision from whoever owns product behavior for blocking — flagging as unresolved, not assigning it to a phase, since no later phase's *code* depends on the answer, but Phase 11 (Safety) should present the same finding from the Safety-module side for a complete picture.

## Phase 06 summary
- 7 findings: **1 Critical (P6-F1), 1 High (P6-F2), 2 Medium (P6-F6, P6-F7), 2 Low (P6-F3, P6-F4), 1 Nice to Have (P6-F5).**
- This phase's Critical finding (block feature doesn't work) is arguably the most consequential single finding in the audit to date — a documented, user-facing safety guarantee that is silently false.
- BUG-004 from the prior audit is fixed for its original scope (auth/impersonation); a different, more severe gap was found in the same neighborhood.
- Nothing found blocks moving on to Phase 07, but Phase 07/09 must specifically check block-enforcement in Post/Feed per the note above.
