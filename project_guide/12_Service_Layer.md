# 12 — Service Layer

## What a "service layer" is, and why it exists as a concept

In a small script, you might put everything in one function: handle the web request, run the business logic, and query the database, all in one place. That works until the app grows — then you need to test the business logic without spinning up a web server, or call the same logic from two different endpoints, or from a background job instead of an HTTP request at all. The **service layer** pattern is the standard answer: put the actual business logic — the rules, the decisions, the sequence of database operations that make up "what does creating a post actually involve" — in its own set of plain functions, separate from the HTTP-handling code. The HTTP layer (the router) becomes a thin adapter: unpack the request, call the service function, wrap the result back into an HTTP response.

## How this app applies it

Every feature module in this codebase follows this split: a `router.py` (or `presentation/router.py`) that defines HTTP endpoints, and a `service.py` (or, for `chat/`/`taste/`, a `domain/use_cases.py` playing the equivalent role — see below) containing the actual logic. You saw this directly in [Request Lifecycle](07_Request_Lifecycle.md)'s worked example: `connections/router.py`'s `follow` function is four lines that call `connections/service.py`'s `follow_user`, which is where every real rule ("can't follow yourself," "can't follow twice," "keep the counters in sync") actually lives.

**The rule of thumb this app follows, almost everywhere:** a router function should be short enough that you could describe everything it does in one sentence without mentioning any business rule — "decode the path parameters, call the service, wrap the response." The moment a router function contains an `if` statement that represents an actual business decision (not just "did validation pass"), that's a sign the logic drifted into the wrong layer.

### Where this is followed cleanly

Almost every router in the app is this thin. `post/router.py`'s `toggle_like_api` is a representative example:
```python
@router.post("/{post_id}/like")
def toggle_like_api(post_id: int, profile_id: int = Depends(get_current_profile_id), db: Session = Depends(get_db)):
    try:
        result = service.toggle_like(db, post_id, profile_id)
        return ok(result, "Like toggled")
    except service.PostNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
```
Nothing here decides *whether* a like should be allowed, or *how* the counter is updated — that's entirely `post/service.py`'s `toggle_like`'s job. The router's only real job beyond plumbing is translating the service's own typed exceptions (`PostNotFoundError`) into the right HTTP status code — a pattern repeated consistently across the app: **services raise their own domain-specific exception classes (not raw `HTTPException` most of the time — see the note on `connections/` below), and routers are where those get translated into HTTP status codes.** This keeps the service layer itself free of any HTTP-specific concepts (a service function doesn't need to know what a "404" is, conceptually) — useful if that same logic were ever called from a non-HTTP context, like a background job.

### An inconsistency worth knowing about

Not every module follows the "services raise typed exceptions, routers translate them" rule strictly. `connections/service.py` raises `HTTPException` directly, from inside the service layer itself, in several places (e.g. `follow_user`'s `raise HTTPException(status_code=400, detail="Cannot follow yourself.")`). This means `connections/service.py` isn't fully HTTP-agnostic the way, say, `post/service.py` is — a minor architectural inconsistency between modules, not a bug (the app behaves correctly either way; a client can't tell the difference), but worth knowing if you're looking for a single, perfectly consistent pattern across every module and are surprised not to find one everywhere.

### The "use case" naming in `chat/` and `taste/`

The two layered modules (see [Modules](11_Modules.md)) don't have a `service.py` at all in their core logic — instead, `domain/use_cases.py` holds one small class per operation (`SendMessageUseCase`, `MarkReadUseCase`, `GetConversationsUseCase`, etc.), each with a single `execute(...)` method. This is the same service-layer *idea* — business logic, separated from HTTP handling — expressed as small classes instead of module-level functions. The practical difference: each use case explicitly receives its dependencies (typically a repository object) through its constructor, rather than a plain function receiving a database session as a parameter directly. This is the same [dependency injection](02_How_the_System_Works.md) concept you already know, just applied one level deeper than "does this endpoint get a database session" — see [Repositories](13_Repositories.md) for what that repository object actually is and why it matters here specifically.

## What belongs in a service function, concretely, in this codebase

Looking across the app, a service function typically does some combination of:
1. **Business-rule checks** that aren't just "is this data shaped correctly" (that's [Pydantic](07_Request_Lifecycle.md)'s job, one layer up) — e.g. "you can't verify a business document before your identity is verified" (`verification/service.py`).
2. **Database reads and writes**, via SQLAlchemy, directly against model classes — most modules have no separate repository layer at all (see [Repositories](13_Repositories.md)) — the service function *is* where the query lives.
3. **Calls to other modules' public functions** — e.g. `post/service.py`'s `create_post` calling into `post_recommendation_module.index_post`.
4. **Calls to external systems** — Redis (fire-and-forget taste signals), Supabase (storage), or a third-party API (Surepass, Groq).
5. **Raising a typed, module-specific exception** on failure, for the router to translate.

## Why this matters when you're adding a new feature

If you're about to add a new capability to an existing module, the service layer is where it goes — not the router. If you're about to add a genuinely new module, look at any of the flat modules (`profile/`, `groups/`, `post/` are all good, representative examples) for the shape to copy: `router.py` importing from `service.py`, `service.py` importing from `models.py`, `schemas.py` defining the request/response shapes both layers agree on.

---
**Previous:** [11 — Modules](11_Modules.md) · **Next:** [13 — Repositories](13_Repositories.md)
