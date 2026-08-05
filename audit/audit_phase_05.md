# Audit Phase 05 — Groups Module

**Status:** Done
**⚠️ Addendum from Phase 11:** P5-F1 (fake report endpoint) is compounded by a Safety-module schema issue — even if Groups' report endpoint were wired to call `safety.service.submit_report`, `target_type="post"` reports would separately fail (Post IDs are integers, `ReportRequest.target_id` requires a UUID). See `audit_phase_11.md`'s P11-F2. Only `target_type="user"` reporting is confirmed to work end-to-end anywhere in the app.
**Scope:** `app/modules/groups/**` — `models.py`, `router.py`, `service.py`, `schemas.py`, `vector.py`

---

## Files inspected

| File | Purpose | Verdict |
|---|---|---|
| `app/modules/groups/models.py` | `Group`, `GroupMember`, `GroupActivityCache`, `GroupEmbedding`, `GroupMedia`, `GroupDeal`, `GroupJoinRequest`, `PersonalDeal` | Live, correct. `GroupDeal`/`PersonalDeal` are intentional near-duplicates (deal fields mirrored for group-context vs. DM-context) — the model docstring itself says so ("Mirrors PostDealDetails fields for clean future extraction"), so not flagging as unplanned duplication. |
| `app/modules/groups/router.py` | 21 endpoints under `/api/v1/groups`, thin HTTP layer via a shared `_handle()` dispatcher | Live, well-organized (explicit route-ordering comments to avoid FastAPI path clashes). See P5-F1 |
| `app/modules/groups/service.py` | All business logic: CRUD, membership, join requests, invite links, media, deals, pgvector-based group suggestions | Live, generally solid. See P5-F1, P5-F2, P5-F3 |
| `app/modules/groups/schemas.py` | Request/response models | Live. See P5-F2 |
| `app/modules/groups/vector.py` | Group embedding build + activity/final score blend (75% semantic + 25% activity) | Live, clean, self-contained. No issues found. |

---

## Reconciliation with `documentation/BACKEND_AUDIT.md` (Groups' bugs: BUG-005, BUG-015)

| Bug | Status now |
|---|---|
| BUG-005 (no auth, `Query(user_id)` everywhere) | **Fixed**, confirmed — every endpoint uses `Depends(get_current_user_id)`/`get_current_user`; matches `auth_and_access_control.md`'s documented table exactly (16 endpoints listed there, all confirmed present). |
| BUG-015 (`list_groups` N+1 membership query per group) | **Fixed**, confirmed — `service.py:389-401` explicitly batches the membership lookup in one `IN`-query for the whole page, with a code comment noting it replaced the old per-row loop. |

---

## Findings

### P5-F1 — `POST /{group_id}/report` doesn't report anything — it's a fake-success endpoint
**Severity:** High
**Category:** Correctness / Missing Connection
**Files:** `app/modules/groups/router.py:504-517` (`report_group_api`)

**Reason:**
```python
@router.post("/{group_id}/report")
def report_group_api(group_id, payload, user_id=..., db=...):
    _handle(get_group, db, group_id, user_id)
    return ok(
        {"group_id": str(group_id), "reason": payload.reason, "status": "submitted"},
        "Report submitted — our team will review it",
    )
```
`_handle(get_group, ...)`'s only purpose here is existence/visibility validation (raises 404 if the group doesn't exist) — its return value is discarded. There is **no call to any persistence layer** anywhere in this function: no `GroupReport` model exists in `groups/models.py`, `service.py` has no `report_group`/`create_report`-style function at all (confirmed — grepped every function name in the service module), and nothing here calls into the Safety module, which already has a working, persisted reporting mechanism (`documentation/security.md` — actually Safety-module docs, see Phase 01/02 note — documents `POST /{user_id}/report` writing to a `user_reports` table with `target_type: user | group | post`, i.e. it already explicitly supports reporting a group).

**Failure scenario:** A user reports a group for fraud/harassment via the UI. The API returns HTTP 200 with `"status": "submitted"` and a reassuring message. Nothing is persisted anywhere. No moderator ever sees it. The reporting user has no way to know their report vanished — the response actively tells them it was "submitted" and "will be reviewed."

**Recommended fix:** Call into the Safety module's report-creation service function from this endpoint (same cross-module pattern already used elsewhere in this codebase — e.g. `connections/service.py` locally importing from `chat.data.repository`/`chat.presentation.connection_manager`), passing `target_type="group", target_id=group_id`. This needs Phase 11 (Safety) to confirm the exact function signature to call, so the fix is correctly wired both ways — flagging as a cross-phase action item.
**Risk:** Low to fix (additive — wiring an existing, working mechanism into a second caller).
**Cleanup effort:** Small (~30–45 min once Safety's service function is confirmed in Phase 11).
**Confidence:** Confirmed (read the full router function and the full service module — no report-persistence code exists anywhere in Groups).

---

### P5-F2 — `Group.category` is accepted and persisted on create/update but never returned in any response
**Severity:** Low
**Category:** Correctness / Dead Field
**Files:** `app/modules/groups/service.py:223-246` (`_build_group_out`), `service.py:290` (`create_group`), `schemas.py:33` (`GroupCreate.category`), `schemas.py:52` (`GroupUpdate.category`)

**Reason:** `GroupCreate.category` and `GroupUpdate.category` both exist and both actually reach the database (`create_group` sets `category=payload.category` on the new `Group` row; `update_group`'s generic `for field, value in data.items(): setattr(group, field, value)` loop applies a `category` update too, since it's not special-cased out). But `_build_group_out()` — the single function every read path (`get_group`, `list_groups`, `create_group`, `update_group`, `get_group_suggestions`) uses to build the response — has the line commented out:
```python
# category=group.category,
```
`GroupOut.category` (schemas.py) is `Optional[str] = None`, so every API response silently reports `category: null` regardless of what's actually stored. The field's own schema comment (`GroupCreate.category: Optional[str] = None # there is no point of category`) suggests whoever wrote it already suspected this field was pointless — but rather than removing it end-to-end, it was partially wired (accepted + persisted) and partially not (never read back), landing in an inconsistent middle state.
**Recommended fix:** This is a two-way decision, not just a code fix: either (a) uncomment `category=group.category` in `_build_group_out` if the field is meant to be used, or (b) remove `category` from `GroupCreate`/`GroupUpdate`/the `Group` model/the migration entirely if it's genuinely pointless, per the schema's own comment. Flagging as a decision point for the user rather than picking one — Not Proven which the frontend actually expects.
**Risk:** Low either way — no data loss in option (a); option (b) needs a migration.
**Cleanup effort:** Trivial for (a) (~5 min); Small for (b) (~30 min incl. migration).
**Confidence:** Confirmed (read `_build_group_out`, both schema classes, and both write paths).

---

### P5-F3 — Redundant duplicate `except` clauses (minor simplification)
**Severity:** Nice to Have
**Category:** Maintainability / Simplification
**Files:** `app/modules/groups/service.py:1324-1329` (`create_group_deal`), `1450-1455` (`publish_group_deal`)

**Reason:** Both functions do:
```python
except (GroupPermissionError, GroupNotFoundError):
    db.rollback()
    raise
except Exception:
    db.rollback()
    raise
```
The first `except` clause is fully redundant — `GroupPermissionError`/`GroupNotFoundError`/`GroupConflictError` are all plain `Exception` subclasses with no special handling here, so the second, more general clause would catch them and do the exact same thing (`db.rollback(); raise`) if the first clause weren't there.
**Recommended fix:** Delete the specific `except` clause in both functions, keep only `except Exception: db.rollback(); raise`.
**Risk:** None (behavior-identical simplification).
**Cleanup effort:** Trivial (~5 min).
**Confidence:** Confirmed (both call sites read in full).

---

## What's solid (no action needed)
- `leave_group`'s "sole admin can't leave" guard (service.py:669-683) is a correct, sensible integrity check with no gaps.
- `_require_admin`/`_require_member`/`_get_membership` are clean, small, reused helpers — no duplicated permission-check logic found across the 21 endpoints (a good contrast to some other modules' repeated inline checks).
- `get_group_suggestions`' two-stage pipeline (pgvector ANN pre-filter → activity-weighted rerank) has a well-reasoned, explicitly commented `ANN_FETCH = 35` constant tied to pgvector's `hnsw.ef_search` default — shows real awareness of a subtle index-bypass performance trap, not just a guessed magic number.
- `list_groups`'s deliberate `# Hard-force public-only discovery for now` override of the `accessibility` filter is a clearly-commented, intentional product decision, not an oversight.
- Group deal creation → optional feed publishing → chat system-card insertion (`create_group_deal`) correctly wraps recommendation-indexing failure in a narrow `try/except Exception: pass` **with an explanatory comment** ("embedding failure must never break deal publishing") — same fail-open pattern flagged elsewhere in this audit as a logging gap, but at least here the intent is explicit; still worth adding a log line for consistency with the fix recommended elsewhere (P4-F3), not repeating as a separate finding.

## Unresolved questions handed to later phases
- P5-F1's fix needs Phase 11 to supply the exact Safety-module function signature for creating a report.
- P5-F2 is a decision point for the user, not purely a later-phase question — noting it here rather than in the open-questions list since no other phase's findings depend on the answer.

## Phase 05 summary
- 3 findings: **1 High (P5-F1), 1 Low (P5-F2), 1 Nice to Have (P5-F3).**
- Both prior-audit bugs assigned to Groups are confirmed fixed.
- Nothing found blocks moving on to Phase 06.
