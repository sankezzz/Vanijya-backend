# Vanijyaa — Safety API Documentation

> **Added:** 2026-04-27
> **Module:** `app/modules/safety/`
> **Tables created:** `user_blocks`, `user_reports`

---

## Overview

Two safety features are supported:

| Feature | Description |
|---------|-------------|
| **Block** | One-directional user block — hides the blocked user from the blocker's feeds, DMs, and recommendations |
| **Report** | Submit a moderation report against a user, group, or post for admin review |

---

## Database Schema

### `user_blocks`

| Column | Type | Notes |
|--------|------|-------|
| `blocker_id` | UUID PK | FK → `users.id` CASCADE |
| `blocked_id` | UUID PK | FK → `users.id` CASCADE |
| `blocked_at` | TIMESTAMPTZ | Set automatically on creation |

- Composite PK `(blocker_id, blocked_id)` prevents duplicate blocks
- Block is **one-directional** — A blocking B does not mean B has blocked A

---

### `user_reports`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INT (auto) PK | |
| `reporter_id` | UUID | FK → `users.id` CASCADE |
| `target_type` | VARCHAR(20) | `user` \| `group` \| `post` |
| `target_id` | UUID | Polymorphic — no hard FK (target may be deleted before review) |
| `reason` | VARCHAR(50) | See valid values below |
| `description` | TEXT | Optional, max 1000 chars |
| `status` | VARCHAR(20) | `pending` → `reviewed` → `actioned` \| `dismissed` |
| `created_at` | TIMESTAMPTZ | Set automatically on creation |
| `reviewed_at` | TIMESTAMPTZ | Set by admin on review |

- Unique constraint on `(reporter_id, target_type, target_id)` — one report per target per user
- Reports are **immutable** once created; only `status` changes via admin action

---

## Base URL

```
/safety
```

---

## Block Endpoints

---

### POST `/{user_id}/block/{target_id}`

Block another user.

**Path params:**

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | The acting user (blocker) |
| `target_id` | UUID | The user to block |

**Responses:**

| Status | Body | When |
|--------|------|------|
| `200` | `{"status": "blocked", "blocked_id": "..."}` | Block created |
| `400` | `{"detail": "Cannot block yourself."}` | `user_id == target_id` |
| `409` | `{"detail": "User is already blocked."}` | Duplicate block |

**Example response:**
```json
{
  "status": "blocked",
  "blocked_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

---

### DELETE `/{user_id}/block/{target_id}`

Remove an existing block.

**Path params:**

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | The acting user |
| `target_id` | UUID | The user to unblock |

**Responses:**

| Status | Body | When |
|--------|------|------|
| `200` | `{"status": "unblocked", "blocked_id": "..."}` | Block removed |
| `404` | `{"detail": "Block not found."}` | No block exists |

---

### GET `/{user_id}/blocked`

List all users blocked by `user_id`, newest first.

**Path params:**

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | The acting user |

**Example response:**
```json
{
  "user_id": "a1b2c3d4-...",
  "total": 2,
  "blocked": [
    {
      "blocked_id": "f1e2d3c4-...",
      "blocked_at": "2026-04-27T10:30:00Z"
    },
    {
      "blocked_id": "b5a4c3d2-...",
      "blocked_at": "2026-04-20T08:15:00Z"
    }
  ]
}
```

---

### GET `/{user_id}/block/status/{target_id}`

Check whether `user_id` has blocked `target_id`. Use this to drive the block/unblock button state in the UI.

**Path params:**

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | The acting user |
| `target_id` | UUID | The user to check |

**Example response:**
```json
{
  "blocker_id": "a1b2c3d4-...",
  "blocked_id": "f1e2d3c4-...",
  "is_blocked": true
}
```

---

## Report Endpoints

---

### POST `/{user_id}/report`

Submit a moderation report for a user, group, or post.

**Path params:**

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | The reporting user |

**Request body:**

```json
{
  "target_type": "user",
  "target_id": "f1e2d3c4-e5f6-7890-abcd-ef1234567890",
  "reason": "spam",
  "description": "This account is sending bulk promotional messages."
}
```

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `target_type` | string | Yes | `user` \| `group` \| `post` |
| `target_id` | UUID | Yes | ID of the user / group / post being reported |
| `reason` | string | Yes | `spam` \| `harassment` \| `inappropriate_content` \| `scam` \| `impersonation` \| `other` |
| `description` | string | No | Free text, max 1000 chars |

**Responses:**

| Status | Body | When |
|--------|------|------|
| `200` | Report object (see below) | Report submitted |
| `400` | `{"detail": "Cannot report yourself."}` | Reporting own user ID |
| `409` | `{"detail": "You have already reported this."}` | Duplicate report |

**Example response:**
```json
{
  "id": 42,
  "target_type": "user",
  "target_id": "f1e2d3c4-...",
  "reason": "spam",
  "status": "pending",
  "created_at": "2026-04-27T11:00:00Z"
}
```

---

### GET `/{user_id}/reports`

List all reports submitted by `user_id`, newest first.

**Path params:**

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | The reporting user |

**Example response:**
```json
{
  "user_id": "a1b2c3d4-...",
  "total": 1,
  "reports": [
    {
      "id": 42,
      "target_type": "group",
      "target_id": "c3d4e5f6-...",
      "reason": "inappropriate_content",
      "status": "pending",
      "created_at": "2026-04-27T11:00:00Z"
    }
  ]
}
```

---

## Report Status Lifecycle

```
pending  ──►  reviewed  ──►  actioned
                        └──►  dismissed
```

| Status | Meaning |
|--------|---------|
| `pending` | Just submitted, awaiting admin review |
| `reviewed` | Admin has seen it, decision in progress |
| `actioned` | Admin took action (user banned, content removed, etc.) |
| `dismissed` | Admin reviewed and found no violation |

---

## Helper Functions (for other modules)

The service layer exposes two utility functions other modules can import to gate access:

```python
from app.modules.safety.service import is_blocked, either_blocked

# True if user_a has specifically blocked user_b
is_blocked(db, blocker_id=user_a, blocked_id=user_b)

# True if EITHER user has blocked the other — use this for DM / feed guards
either_blocked(db, user_a=user_a, user_b=user_b)
```
