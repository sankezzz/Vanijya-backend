# 13 — Repositories

## What the "repository pattern" is, and why you'd want one

A **repository** is an object whose entire job is talking to the database on behalf of a specific kind of data — nothing else. The idea is to draw a hard line between "how do I fetch/save a Conversation" and "what are the business rules about conversations" — the business-logic code asks a repository object for what it needs (`repo.get_conversation(id)`) without knowing or caring whether that's backed by SQLAlchemy, a different database entirely, or an in-memory fake used in a test. The benefit this is meant to buy you: business logic becomes testable without a real database (swap in a fake repository that returns canned data), and if the underlying storage technology ever changed, only the repository's internals would need to change, not every place that uses it.

This is a genuinely different, stronger commitment than the [Service Layer](12_Service_Layer.md) pattern by itself. A service function can call `db.query(...)` directly and still be "a service" — that's what almost every module in this app does. A *repository* specifically means that database access is pulled into its own dedicated class, and the business-logic layer never imports a SQLAlchemy model or writes a query itself.

## Where this app actually has one — and where it doesn't

**Most of this codebase does not use a real repository layer.** `profile/service.py`, `connections/service.py`, `groups/service.py`, `post/service.py`, and most others call `db.query(SomeModel)...` directly, inline, in the same function that also contains the business rule. This is a completely valid, common alternative to the repository pattern for an app of this size — not a mistake, and this handbook isn't grading it as one. It just means "Repositories," as a distinct architectural layer, describes only two modules in this app.

**`app/modules/chat/`** has a genuine repository: `data/repository.py`'s `ChatRepository` class. Every database query chat needs — building a conversation list, fetching a page of messages, checking membership, building a share-recipients list — is a method on this one class. `domain/use_cases.py`'s classes (`SendMessageUseCase`, `MarkReadUseCase`, etc.) each take a repository object in their constructor and only ever call methods on it — never `db.query(...)` directly. This is the real pattern, correctly applied:

```python
class MarkReadUseCase:
    def __init__(self, repo):
        self.repo = repo

    def execute(self, user_id, conv_id):
        if not self.repo.is_member(conv_id, user_id):
            raise HTTPException(status_code=403, detail="the user is not a part of this convo")
        return self.repo.mark_read(conv_id, user_id)
```
`MarkReadUseCase` has no idea `ChatRepository` uses SQLAlchemy underneath. Nothing about this class would need to change if the storage technology did.

**`app/modules/taste/`** has three repositories, one per layer of its architecture — `RedisModuleSessionRepository`, `RedisGlobalSessionRepository`, `PostgresGlobalTasteRepository` — each implementing a small interface (`IModuleSessionRepository`, `IGlobalSessionRepository`, `IGlobalTasteRepository`, defined in each layer's own `domain/interfaces.py`). This is the most textbook-correct application of the pattern anywhere in the app: the application layer (`aggregator.py`'s `MergeWeights`/`SyncModuleToGlobal`, `use_cases.py`'s `PromoteFromGlobalSession`) is written entirely against those interfaces, never against a concrete Redis or PostgreSQL detail. Full explanation of what these three repositories actually store in [Recommendation Engine](19_Recommendation_Engine.md).

## Why an *interface* matters here, concretely

You've seen `Depends(...)` as a way to inject a *value* (a database session, the current user) into a function. The repository pattern, as used in `chat/` and `taste/`, extends the same underlying idea to injecting a *behavior*. `IGlobalSessionRepository` (`taste/global_session/domain/interfaces.py`) is an **abstract base class** — it declares method names and signatures (`write_dimension_delta`, `read_dimension_weights`, ...) with no implementation, purely a contract. `RedisGlobalSessionRepository` is the one and only class in this codebase that actually implements that contract today. Nothing stops a test (or a future alternative backend) from writing a second class implementing the same contract differently — the `MergeWeights` code that consumes it wouldn't need to change at all. **Not verified from the current implementation:** whether this app's test suite (see [Known Limitations](30_Known_Limitations.md) for its current broken state) actually exercises this by supplying a fake repository — the *capability* is real and correctly built; whether it's currently exploited by any test is a separate question this handbook can't confirm.

## A practical rule for when you're adding code to one of these two modules

If you're adding a new database query to `chat/` or `taste/`, it belongs as a new method on the relevant repository class — not inline inside a use case. If you're adding a new database query to almost any *other* module, follow that module's existing convention instead (a `db.query(...)` call directly inside the relevant `service.py` function) — introducing a repository class into a module that doesn't have one, for just one new query, would make that one module inconsistent with itself rather than more correct.

---
**Previous:** [12 — Service Layer](12_Service_Layer.md) · **Next:** [14 — Authentication](14_Authentication.md)
