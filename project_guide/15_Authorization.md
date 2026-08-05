# 15 — Authorization

[Authentication](14_Authentication.md) answers "who is making this request." **Authorization** answers a different question: "is this specific, correctly-identified person allowed to do this specific thing, to this specific resource?" A request can pass authentication perfectly (a valid, unexpired access token) and still need to be rejected — because the person is real, but not the right person for what they're asking to do.

This app has no separate "authorization module" or permission framework — there is no `@requires_permission("posts:delete")` decorator anywhere. Every authorization decision is hand-written, inline, inside the relevant service function, using whatever data model already expresses the relevant relationship (an author ID on a post, a membership row in a group, a receiver ID on a request). That's a legitimate, common way to build this for an app of this size — but it also means the check is only as good as whoever remembered to write it for that specific endpoint, and this chapter documents exactly where that held up and where it verifiably didn't.

## The three shapes this takes in the codebase

### Shape 1 — fetch the resource, then compare an ID

The most common pattern: load the row, then compare one of its columns against the caller's identity, and raise a typed exception if they don't match. `post/service.py`'s `update_post` and `delete_post` are representative:
```python
def update_post(db: Session, post_id: int, profile_id: int, payload: PostUpdate) -> PostResponse:
    post = _get_post_or_raise(db, post_id)
    if post.profile_id != profile_id:
        raise PostForbiddenError("You can only edit your own posts")
```
(`app/modules/post/service.py:511-514`, and identically at `:529-532` for `delete_post`, `:738` for comment ownership, `:883` for another post-scoped action.) Per the [Service Layer](12_Service_Layer.md) pattern, `PostForbiddenError` is a typed exception the router translates to an HTTP status — this app's convention is 403 for "you're allowed to be here, but not to do this."

### Shape 2 — bake the ownership check straight into the query filter

`connections/service.py`'s `respond_to_request` (accept/decline a follow request) does the equivalent check differently — instead of fetching the row and comparing afterward, the "must be the receiver" condition is one of the `WHERE` clauses of the fetch itself:
```python
req = db.query(MessageRequest).filter(
    MessageRequest.id == request_id,
    MessageRequest.receiver_id == me,
    MessageRequest.status == "pending",
).first()
if not req:
    raise HTTPException(
        status_code=404,
        detail="Request not found, already acted on, or you are not the receiver.",
    )
```
(`app/modules/connections/service.py:377-386`.) Functionally this achieves the same authorization goal as Shape 1, but with a side effect worth noticing: someone who isn't the receiver gets the *same* 404 as someone who guessed a request ID that doesn't exist at all — a caller can't distinguish "this doesn't exist" from "this exists but isn't yours." That's a reasonable, arguably preferable outcome for this specific case (it avoids confirming a given request ID is real to someone who shouldn't be looking at it), but it's a different failure mode than Shape 1's explicit 403, and worth knowing about if you're debugging "why is this 404 instead of 403."

### Shape 3 — a resource-scoped role, not a platform-wide one

Groups are the one place in this app with a real, working role system — but it's scoped to a single group, not the whole platform. `GroupMember.role` is either `"admin"` or `"member"`; `groups/service.py` defines two small helpers used throughout the module:
```python
def _require_admin(db: Session, group_id: UUID, user_id: UUID) -> None:
    membership = _get_membership(db, group_id, user_id)
    if not membership or membership.role != "admin":
        raise GroupPermissionError("Admin access required")

def _require_member(db: Session, group_id: UUID, user_id: UUID) -> None:
    membership = _get_membership(db, group_id, user_id)
    if not membership:
        raise GroupPermissionError("Must be a group member")
```
(`app/modules/groups/service.py:210-219`.) `_require_admin` gates group-management actions — updating group settings, removing a member, deleting the group, approving join requests (called at `service.py:417, 439, 453, 540, 570, 751, 768, 790`). The group's creator is automatically seeded as its first `"admin"` member at creation time (`service.py:301`). This is a genuinely correct, resource-scoped authorization system — it just doesn't extend anywhere outside the `groups/` module, and there's no "platform admin" equivalent of it (see below).

Chat uses the simplest version of this idea — binary membership, no roles within it: `ChatRepository.is_member(conv_id, user_id)` (`app/modules/chat/data/repository.py:640-645`) checks for a `ConversationMember` row and is consulted before any read or write on a conversation, exactly as shown in [Repositories](13_Repositories.md)' `MarkReadUseCase` example.

## The `roles` table is a business classification, not a permission system — a distinction worth being precise about

`profile/models.py` defines a `Role` table (Trader / Broker / Exporter, seeded data — see [Database Guide](09_Database_Guide.md) §1). It's easy to assume a table named `Role` is what gates admin-style actions. **It is not, anywhere in this codebase.** It's a *business* classification a profile picks during onboarding, used for two things: display, and as the mechanism behind `Post.target_roles` (a post's author can mark it "Brokers only," say) — a content-targeting feature, not a permission boundary on the app's own operations. Whether that content-targeting actually works as an access control is a separate, important question, covered next.

## Visibility is authorization too — and this is where the sharpest verified gap is

"Can this user *see* this data" is as much an authorization question as "can this user *edit* this data," and the audit's Phase 11 pass found a serious, precisely-verified gap here: `Post.is_public` ("True=all users, False=followers only") and `Post.target_roles` ("null=all roles, otherwise specific role IDs") are real, stored, serialized columns — but they are enforced as an actual read-time filter in exactly **one** of at least four places that serve post content:

| Code path | Serves | `is_public` enforced? | `target_roles` enforced? |
|---|---|---|---|
| `_get_post_or_raise` (single-post fetch — backs `GET /posts/{id}`, likes, comments, saves, shares) | Nearly every single-post operation | No | No |
| `get_following_feed` | Following feed | No | No |
| `_query_partition` (`post_recommendation_module/service.py`) | Main recommendation-feed candidate pool | No | Baked into the similarity vector only — nudges ranking, doesn't exclude |
| `_ensure_fresh_in_pool` (`post_recommendation_module/service.py`) | Supplementary "keep new posts from being ANN-starved" path | **Yes** — hard `WHERE is_public = true` | **Yes** — Python-side role check |
| `deeplink/service.py`'s `get_post_share_link` (backs the fully unauthenticated `GET /share/post/{post_id}`) | Public share links | No | No |

(Full evidence: `audit/audit_phase_11.md`, finding P11-F1.) **Concretely:** a post marked "followers only" is still fetchable directly by ID by any logged-in user, still appears in a follower's following feed regardless of role, and its title/caption/image are retrievable by *anyone on the internet, logged in or not*, by guessing a nearby integer post ID on the share-link endpoint — post IDs are sequential. This isn't a hypothetical: the columns exist, are set by real user action (choosing "followers only" when creating a post), and are silently not honored in the paths that matter most.

## There is no platform-wide admin role — and two verified consequences

This app has no concept of "an admin user" at the platform level — no `is_admin` column on `User`, no admin role, no allowlist. That absence has two concrete, verified consequences, of different severity:

**`/news/admin/*` — real, but only "any logged-in user," not an admin (P8-F1).** `ingestion/router.py` names its prefix `/news/admin` (`app/modules/news_new/ingestion/router.py:21`), which reads as admin-gated — but every route on it depends only on `Depends(get_current_user_id)`:
```python
@router.post("/ingest")
def trigger_ingest(..., _user_id: UUID = Depends(get_current_user_id), db: Session = Depends(get_db)):
```
(`ingestion/router.py:24-30`, and identically for `/enrich` and `/stats`.) Any authenticated user — not just an operator — can trigger a live GNews fetch, up to 100 metered Groq LLM enrichment calls in one request, or view internal pipeline counts. The `_user_id` parameter is even prefixed with an underscore, signaling it's fetched only to satisfy the dependency, not because the handler uses the value for anything (there is no check of *which* user it is).

**Four Post-module job endpoints require no authentication at all — not even login (P13-F1).** This is one level worse: `post_recommendation_module/router.py:55-64` and `post_user_interaction/router.py:46-57` expose `/jobs/expiry`, `/jobs/popular-sync`, `/jobs/taste-update`, and `/jobs/ignore-detect`, each with exactly one dependency:
```python
@router.post("/jobs/expiry", response_model=JobResult)
def trigger_expiry_job(db: Session = Depends(get_db)):
    result = jobs.run_expiry_job(db)
    return JobResult(status="ok", details=result)
```
No `Depends(get_current_user_id)`, no credential of any kind. Each one directly invokes a real, DB-writing background job (the same jobs [Background Jobs](18_Background_Jobs.md) covers as scheduled work) — on demand, from any internet request, by anyone. Both routers are mounted in `main.py` (see [Startup Process](05_Startup_Process.md)), so these are live endpoints in the deployed app today.

Both findings point at the same missing piece: **this app has never needed to decide what "admin" means**, so nobody has had to build it, and these routes were most likely written as convenient manual/ops triggers during development and never revisited before being merged onto the public router. See [Known Limitations](30_Known_Limitations.md).

## Chat has no block-enforcement anywhere in its authorization checks

Searching `chat/data/repository.py` for any reference to blocking (`is_blocked`, `UserBlock`, or similar) returns nothing — `is_member` is the *only* gate chat applies to reads and writes on a conversation. This independently confirms, from the chat side, the same gap the audit's Phase 06 pass found from the connections/blocking side (P6-F1: the block feature's enforcement is non-functional) — a user who has blocked someone, or been blocked by them, is not prevented from exchanging messages by anything in the chat authorization path itself. See [Feature Guide](10_Feature_Guide.md)'s Safety section for the full picture of what blocking currently does and doesn't do.

**A working counter-example, so this doesn't read as "nothing is enforced":** `connections/service.py`'s `_activate_dm` (called when a message request is accepted) explicitly refuses to silently revive a `BLOCKED`-status conversation:
```python
# Never revive a blocked conversation — an explicit block must not be
# silently undone by accepting a message request.
if conv.status == ConvStatus.BLOCKED:
    raise HTTPException(status_code=403, detail="This conversation is blocked.")
```
(`app/modules/connections/service.py:452-455`.) So blocking *is* correctly respected in this one specific path (re-accepting a request can't undo a block) — the gap is that this is close to the only place it's checked at all, not that the concept is entirely unimplemented everywhere.

## Deciding which shape a new endpoint needs

```mermaid
flowchart TD
    A[Adding a new endpoint that\nacts on an existing resource] --> B{Does only the\nresource's owner\nact on it?}
    B -->|Yes| C[Shape 1 or 2:\ncompare an ID field,\nor bake it into the WHERE clause\ne.g. post ownership, request receiver]
    B -->|No| D{Is it scoped to\nmembership in something\nshared, e.g. a group\nor conversation?}
    D -->|Yes, any member| E[Membership check\ne.g. ChatRepository.is_member]
    D -->|Yes, only certain members| F[Resource-scoped role check\ne.g. groups._require_admin]
    D -->|No, it's an operational\n/ops-only endpoint| G[STOP: this app has\nno admin-role mechanism yet.\nDo not ship it "temporarily"\nauth-free — see P8-F1 / P13-F1]
```

If you're adding an endpoint that genuinely needs "only an operator, not any user" — the honest current answer is that this app doesn't yet have a building block for that. Don't reach for the `roles` table (that's a business classification, not a permission system, per above); don't ship it gated by nothing "temporarily," per the two findings above already sitting in production that way. Flag it as a decision point rather than inventing a one-off mechanism.

---
**Previous:** [14 — Authentication](14_Authentication.md) · **Next:** [16 — Caching](16_Caching.md)
