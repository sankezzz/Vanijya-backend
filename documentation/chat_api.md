# Chat Module — API Documentation

**Base URL:** `https://vanijyaa-backend.onrender.com`  
**All responses follow the envelope format:**

```json
{
  "success": true,
  "message": "...",
  "data": { ... }
}
```

**No auth token required — the acting user is always identified by `{user_id}` in the URL path.**

---

## Table of Contents

### Direct Messages (DM)
1. [List Conversations](#1-list-conversations)
2. [Open DM / Send First Message](#2-open-dm--send-first-message)
3. [Get DM Message History](#3-get-dm-message-history)
4. [Send DM Message](#4-send-dm-message)
5. [Accept Chat Request](#5-accept-chat-request)
6. [Decline Chat Request](#6-decline-chat-request)
7. [Mark Conversation Read](#7-mark-conversation-read)

### Group Chat
8. [Get Group Message History](#8-get-group-message-history)
9. [Send Group Message](#9-send-group-message)

### Real-time
10. [WebSocket — Live Push](#10-websocket--live-push)

### Reference
- [Conversation Object](#conversation-object)
- [Message Object](#message-object)
- [Conversation Status Reference](#conversation-status-reference)
- [Message Type Reference](#message-type-reference)
- [Error Reference](#error-reference)
- [DM Flow Diagram](#dm-flow-diagram)
- [Testing Checklist](#testing-checklist)
- [Integration Notes for Frontend](#integration-notes-for-frontend)

---

## Conversation Object

Returned by list/open/accept/decline endpoints.

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "requested",
  "participant": {
    "user_id": "b2c3d4e5-...",
    "profile_id": 12,
    "name": "Rajesh Mehta",
    "is_verified": true
  },
  "last_message": {
    "id": "c3d4e5f6-...",
    "body": "Hey! Want to connect?",
    "message_type": "text",
    "sender_id": "a1b2c3d4-...",
    "sent_at": "2026-04-21T10:30:00+00:00"
  },
  "unread_count": 1,
  "is_muted": false,
  "created_at": "2026-04-21T10:30:00+00:00",
  "updated_at": "2026-04-21T10:30:00+00:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID string | Conversation ID |
| `status` | string | `"requested"` \| `"active"` \| `"blocked"` — see [Conversation Status Reference](#conversation-status-reference) |
| `participant` | object | The **other** person in the DM (not the requesting user) |
| `participant.user_id` | UUID string | Other user's UUID |
| `participant.profile_id` | int | Other user's profile ID |
| `participant.name` | string | Other user's display name |
| `participant.is_verified` | bool | Whether the other user is verified |
| `last_message` | object \| null | Most recent message in the conversation |
| `unread_count` | int | Messages received since the requesting user last called mark-read |
| `is_muted` | bool | Whether the requesting user has muted this conversation |
| `created_at` | datetime | ISO 8601 UTC |
| `updated_at` | datetime | ISO 8601 UTC — bumped on every new message |

---

## Message Object

Returned by send/get-messages endpoints. Same shape for both DM and group messages.

```json
{
  "id": "d4e5f6a7-...",
  "context_id": "3fa85f64-...",
  "context_type": "dm",
  "sender": {
    "user_id": "a1b2c3d4-...",
    "profile_id": 5,
    "name": "Sanket S.",
    "is_verified": true
  },
  "message_type": "text",
  "body": "Hey! Want to connect?",
  "media_url": null,
  "media_metadata": null,
  "location_lat": null,
  "location_lon": null,
  "reply_to_id": null,
  "is_deleted": false,
  "sent_at": "2026-04-21T10:30:00+00:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID string | Message ID |
| `context_id` | UUID string | The conversation ID (DM) or group ID (group) this message belongs to |
| `context_type` | string | `"dm"` or `"group"` |
| `sender` | object | Sender's profile snapshot (same shape as `participant`) |
| `message_type` | string | See [Message Type Reference](#message-type-reference) |
| `body` | string \| null | Text content — required for `text` type, optional for media types |
| `media_url` | string \| null | URL of the media file — required for `image`, `video`, `audio`, `document` |
| `media_metadata` | object \| null | Optional extra metadata (dimensions, duration, etc.) |
| `location_lat` | float \| null | Latitude — for `location` type |
| `location_lon` | float \| null | Longitude — for `location` type |
| `reply_to_id` | UUID string \| null | ID of the message being replied to |
| `is_deleted` | bool | `true` if the message was soft-deleted |
| `sent_at` | datetime | ISO 8601 UTC |

---

## Conversation Status Reference

| Status | Meaning | Who can send |
|--------|---------|--------------|
| `requested` | User A opened the DM — waiting for User B to accept | Only the **initiator** (User A) |
| `active` | User B accepted the request — full two-way chat | Both users |
| `blocked` | User B declined — conversation is closed | Nobody (403 on send) |

---

## Message Type Reference

| `message_type` | `body` | `media_url` | Notes |
|----------------|--------|-------------|-------|
| `text` | Required | — | Plain text message |
| `image` | Optional caption | Required | Photo |
| `video` | Optional caption | Required | Video clip |
| `audio` | — | Required | Voice note |
| `document` | Optional caption | Required | PDF / file |
| `location` | Optional label | — | Use `location_lat` + `location_lon` |
| `system` | Required | — | System-generated messages (not sent by users) |

---

---

# Direct Message (DM) Endpoints

---

## 1. List Conversations

**`GET /api/v1/chat/{user_id}/conversations`**

Returns all conversations (DMs) for the user — both `requested` and `active` — sorted by most recently updated.

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | Acting user's UUID |

### Query Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | `1` | Page number (1-based) |
| `per_page` | int | `20` | Items per page (max 100) |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Conversations fetched",
  "data": {
    "conversations": [
      {
        "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "status": "active",
        "participant": {
          "user_id": "b2c3d4e5-...",
          "profile_id": 12,
          "name": "Rajesh Mehta",
          "is_verified": true
        },
        "last_message": {
          "id": "c3d4e5f6-...",
          "body": "Sure, let's connect!",
          "message_type": "text",
          "sender_id": "b2c3d4e5-...",
          "sent_at": "2026-04-21T11:00:00+00:00"
        },
        "unread_count": 2,
        "is_muted": false,
        "created_at": "2026-04-21T10:30:00+00:00",
        "updated_at": "2026-04-21T11:00:00+00:00"
      }
    ],
    "page": 1,
    "per_page": 20
  }
}
```

### Errors

| Status | Reason |
|--------|--------|
| `422` | Missing or invalid `user_id` |

---

## 2. Open DM / Send First Message

**`POST /api/v1/chat/{user_id}/conversations`**

Opens a new DM with another user and sends the first message.  
**Idempotent** — if a DM between the two users already exists, returns the existing conversation and adds the message to it.

> When a new conversation is created, the `status` is `"requested"` until the other party accepts. Only the initiator can send follow-up messages while the status is `requested`.

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | Acting user's UUID (the initiator) |

### Request Body

```json
{
  "participant_id": "b2c3d4e5-f6a7-...",
  "message": "Hey! Want to connect?"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `participant_id` | UUID | Yes | The other user's UUID |
| `message` | string | Yes | First message body (1–4000 characters) |

### Response — `201 Created`

```json
{
  "success": true,
  "message": "Chat opened",
  "data": {
    "conversation": {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "status": "requested",
      "participant": {
        "user_id": "b2c3d4e5-...",
        "profile_id": 12,
        "name": "Rajesh Mehta",
        "is_verified": true
      },
      "last_message": { "..." : "..." },
      "unread_count": 0,
      "is_muted": false,
      "created_at": "2026-04-21T10:30:00+00:00",
      "updated_at": "2026-04-21T10:30:00+00:00"
    },
    "message": { "...full message object..." },
    "created": true
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `conversation` | object | The conversation — see [Conversation Object](#conversation-object) |
| `message` | object | The first message — see [Message Object](#message-object) |
| `created` | bool | `true` = new conversation created; `false` = existing conversation returned |

> **Side effect:** A `new_message` WebSocket event is pushed to `participant_id` if they are connected.

### Errors

| Status | Reason |
|--------|--------|
| `400` | `participant_id` is the same as `user_id` (cannot chat with yourself) |
| `403` | Conversation exists but is `"blocked"` |
| `422` | Missing or invalid fields |

---

## 3. Get DM Message History

**`GET /api/v1/chat/{user_id}/conversations/{conv_id}/messages`**

Returns messages for a conversation, newest first. Supports cursor-based pagination via the `before` timestamp.

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | Acting user's UUID — must be a member of this conversation |
| `conv_id` | UUID | Conversation ID |

### Query Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `before` | datetime | — | ISO 8601 timestamp — fetch messages older than this. Omit for the latest messages |
| `limit` | int | `50` | Number of messages to return (max 100) |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Messages fetched",
  "data": {
    "messages": [
      {
        "id": "d4e5f6a7-...",
        "context_id": "3fa85f64-...",
        "context_type": "dm",
        "sender": {
          "user_id": "b2c3d4e5-...",
          "profile_id": 12,
          "name": "Rajesh Mehta",
          "is_verified": true
        },
        "message_type": "text",
        "body": "Sure, let's connect!",
        "media_url": null,
        "media_metadata": null,
        "location_lat": null,
        "location_lon": null,
        "reply_to_id": null,
        "is_deleted": false,
        "sent_at": "2026-04-21T11:00:00+00:00"
      }
    ],
    "has_more": false,
    "oldest_timestamp": "2026-04-21T10:30:00+00:00"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `messages` | array | Messages, newest first |
| `has_more` | bool | `true` if there are older messages — pass `oldest_timestamp` as `before` to fetch them |
| `oldest_timestamp` | datetime \| null | ISO 8601 timestamp of the oldest message in this page — use as `before` cursor for the next page |

### Pagination Flow

```
First call (no before):
  GET /conversations/{conv_id}/messages?limit=50
  → returns latest 50 messages + oldest_timestamp

Load older messages:
  GET /conversations/{conv_id}/messages?before=<oldest_timestamp>&limit=50
  → returns the next 50 older messages

When has_more is false → no more history.
```

### Errors

| Status | Reason |
|--------|--------|
| `403` | `user_id` is not a member of the conversation |

---

## 4. Send DM Message

**`POST /api/v1/chat/{user_id}/conversations/{conv_id}/messages`**

Sends a message in an existing conversation.

> **Send gate:**
> - `requested` → only the **initiator** may send (the other user must accept first)
> - `active` → both users may send freely
> - `blocked` → nobody may send

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | Sender's UUID |
| `conv_id` | UUID | Conversation ID |

### Request Body

```json
{
  "body": "Here is the deal breakdown.",
  "message_type": "text",
  "media_url": null,
  "media_metadata": null,
  "location_lat": null,
  "location_lon": null,
  "reply_to_id": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message_type` | string | Yes | See [Message Type Reference](#message-type-reference) — defaults to `"text"` |
| `body` | string | Conditional | Required for `text`. Max 4000 characters |
| `media_url` | string | Conditional | Required for `image`, `video`, `audio`, `document`. Max 500 characters |
| `media_metadata` | object | No | Optional extra info (e.g. `{"duration_s": 12, "width": 1080}`) |
| `location_lat` | float | Conditional | Required for `location` type |
| `location_lon` | float | Conditional | Required for `location` type |
| `reply_to_id` | UUID | No | ID of the message being replied to |

### Response — `201 Created`

```json
{
  "success": true,
  "message": "Message sent",
  "data": {
    "message": {
      "id": "e5f6a7b8-...",
      "context_id": "3fa85f64-...",
      "context_type": "dm",
      "sender": { "..." : "..." },
      "message_type": "image",
      "body": "Check this out",
      "media_url": "https://cdn.example.com/img.jpg",
      "media_metadata": null,
      "location_lat": null,
      "location_lon": null,
      "reply_to_id": null,
      "is_deleted": false,
      "sent_at": "2026-04-21T11:05:00+00:00"
    }
  }
}
```

> **Side effect:** A `new_message` WebSocket event is pushed to the other participant if connected.

### Errors

| Status | Reason |
|--------|--------|
| `403` | Conversation is `blocked`; or sender is the non-initiator and status is `requested` |
| `404` | Conversation not found or `user_id` is not a member |
| `422` | Validation error (e.g. missing `body` for text, missing `media_url` for image) |

---

## 5. Accept Chat Request

**`POST /api/v1/chat/{user_id}/conversations/{conv_id}/accept`**

The receiver accepts the chat request. Sets conversation status from `requested` → `active`. After this, both users can send messages freely.

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | The receiving user's UUID (the one who got the request) |
| `conv_id` | UUID | Conversation ID |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Chat request accepted",
  "data": {
    "conversation": {
      "id": "3fa85f64-...",
      "status": "active",
      "..."  : "..."
    }
  }
}
```

### Errors

| Status | Reason |
|--------|--------|
| `404` | Conversation not found or `user_id` is not a member |
| `409` | Conversation is already `active` or `blocked` (cannot accept twice) |

---

## 6. Decline Chat Request

**`POST /api/v1/chat/{user_id}/conversations/{conv_id}/decline`**

The receiver declines the chat request. Sets status from `requested` → `blocked`. After this, neither user can send messages.

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | The receiving user's UUID |
| `conv_id` | UUID | Conversation ID |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Chat request declined",
  "data": {
    "conversation": {
      "id": "3fa85f64-...",
      "status": "blocked",
      "..."  : "..."
    }
  }
}
```

### Errors

| Status | Reason |
|--------|--------|
| `404` | Conversation not found or `user_id` is not a member |
| `409` | Conversation is already `active` or `blocked` (cannot decline again) |

---

## 7. Mark Conversation Read

**`POST /api/v1/chat/{user_id}/conversations/{conv_id}/read`**

Marks all messages in the conversation as read for `user_id`. Resets the unread count to `0` for this user.

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | Acting user's UUID |
| `conv_id` | UUID | Conversation ID |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Marked as read",
  "data": null
}
```

### Errors

| Status | Reason |
|--------|--------|
| `403` | `user_id` is not a member of the conversation |

---

---

# Group Chat Endpoints

Group chat messages use the same [Message Object](#message-object) as DM — only `context_type` is `"group"` and `context_id` points to the group's UUID.

> **Group membership is required.** Only users who have joined a group (via the Groups API) can send or read messages. Frozen members cannot send.  
> If `chat_perm` is `"admins_only"` on the group, only admins can send messages.

---

## 8. Get Group Message History

**`GET /api/v1/chat/{user_id}/groups/{group_id}/messages`**

Returns messages for a group chat, newest first. Same cursor-based pagination as DM history.

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | Acting user's UUID — must be a group member |
| `group_id` | UUID | Group ID |

### Query Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `before` | datetime | — | ISO 8601 timestamp cursor — fetch messages older than this |
| `limit` | int | `50` | Number of messages (max 100) |

### Response — `200 OK`

```json
{
  "success": true,
  "message": "Group messages fetched",
  "data": {
    "messages": [
      {
        "id": "f6a7b8c9-...",
        "context_id": "g1r2o3u4-...",
        "context_type": "group",
        "sender": {
          "user_id": "a1b2c3d4-...",
          "profile_id": 5,
          "name": "Sanket S.",
          "is_verified": true
        },
        "message_type": "text",
        "body": "Hello group!",
        "media_url": null,
        "media_metadata": null,
        "location_lat": null,
        "location_lon": null,
        "reply_to_id": null,
        "is_deleted": false,
        "sent_at": "2026-04-21T12:00:00+00:00"
      }
    ],
    "has_more": true,
    "oldest_timestamp": "2026-04-21T12:00:00+00:00"
  }
}
```

### Errors

| Status | Reason |
|--------|--------|
| `403` | `user_id` is not a member of the group |

---

## 9. Send Group Message

**`POST /api/v1/chat/{user_id}/groups/{group_id}/messages`**

Sends a message in a group chat.

> **Send rules:**
> - Sender must be a group member
> - Sender must not be frozen in the group
> - If the group's `chat_perm` is `"admins_only"`, only admins can send

### Path Parameters

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | Sender's UUID |
| `group_id` | UUID | Group ID |

### Request Body

```json
{
  "body": "Big rice deal available — 500MT at ₹28/kg",
  "message_type": "text",
  "media_url": null,
  "media_metadata": null,
  "reply_to_id": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message_type` | string | Yes | See [Message Type Reference](#message-type-reference) — defaults to `"text"` |
| `body` | string | Conditional | Required for `text`. Max 4000 characters |
| `media_url` | string | Conditional | Required for `image`, `video`, `audio`, `document`. Max 500 characters |
| `media_metadata` | object | No | Optional extra info |
| `reply_to_id` | UUID | No | ID of the message being replied to |

> **Note:** Group messages do not have `location_lat` / `location_lon` — use `message_type: "location"` with body for a location label if needed.

### Response — `201 Created`

```json
{
  "success": true,
  "message": "Group message sent",
  "data": {
    "message": {
      "id": "a7b8c9d0-...",
      "context_id": "g1r2o3u4-...",
      "context_type": "group",
      "sender": {
        "user_id": "a1b2c3d4-...",
        "profile_id": 5,
        "name": "Sanket S.",
        "is_verified": true
      },
      "message_type": "image",
      "body": "Check the price board",
      "media_url": "https://cdn.example.com/board.jpg",
      "media_metadata": null,
      "location_lat": null,
      "location_lon": null,
      "reply_to_id": null,
      "is_deleted": false,
      "sent_at": "2026-04-21T12:05:00+00:00"
    }
  }
}
```

> **Side effect:** A `new_group_message` WebSocket event is pushed to all online group members (excluding the sender).

### Errors

| Status | Reason |
|--------|--------|
| `403` | Sender is not a member, is frozen, or group has `chat_perm: admins_only` and sender is not admin |
| `404` | Group not found |
| `422` | Validation error |

---

---

# WebSocket — Live Push

## 10. WebSocket — Live Push

**`WS /ws/chat/{user_id}`**

Establishes a persistent WebSocket connection for real-time message delivery.

Connect once per user session. All incoming messages across all DMs and group chats are delivered through this single connection.

### Connection

```
ws://localhost:8000/ws/chat/{user_id}
wss://vanijyaa-backend.onrender.com/ws/chat/{user_id}
```

| Param | Type | Description |
|-------|------|-------------|
| `user_id` | UUID | The connected user's UUID |

The server accepts the connection immediately — no handshake payload required. Send any text frame (e.g. `"ping"`) to keep the connection alive.

---

### Event — `new_message` (DM)

Pushed to the **receiver** when the other party sends a DM message.

```json
{
  "event": "new_message",
  "data": {
    "conversation_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "message": {
      "id": "d4e5f6a7-...",
      "context_id": "3fa85f64-...",
      "context_type": "dm",
      "sender": {
        "user_id": "a1b2c3d4-...",
        "profile_id": 5,
        "name": "Sanket S.",
        "is_verified": true
      },
      "message_type": "text",
      "body": "Hey! Want to connect?",
      "media_url": null,
      "media_metadata": null,
      "location_lat": null,
      "location_lon": null,
      "reply_to_id": null,
      "is_deleted": false,
      "sent_at": "2026-04-21T10:30:00+00:00"
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `event` | Always `"new_message"` for DM events |
| `data.conversation_id` | Which conversation this message belongs to |
| `data.message` | Full [Message Object](#message-object) |

---

### Event — `new_group_message` (Group Chat)

Pushed to **all online group members** (except the sender) when a group message is sent.

```json
{
  "event": "new_group_message",
  "data": {
    "group_id": "g1r2o3u4-p5q6-...",
    "message": {
      "id": "f6a7b8c9-...",
      "context_id": "g1r2o3u4-...",
      "context_type": "group",
      "sender": {
        "user_id": "a1b2c3d4-...",
        "profile_id": 5,
        "name": "Sanket S.",
        "is_verified": true
      },
      "message_type": "text",
      "body": "Hello group!",
      "media_url": null,
      "media_metadata": null,
      "location_lat": null,
      "location_lon": null,
      "reply_to_id": null,
      "is_deleted": false,
      "sent_at": "2026-04-21T12:00:00+00:00"
    }
  }
}
```

| Field | Description |
|-------|-------------|
| `event` | Always `"new_group_message"` for group events |
| `data.group_id` | Which group this message belongs to |
| `data.message` | Full [Message Object](#message-object) |

---

### Connection Lifecycle

```
Client                        Server
  |                             |
  |── WS connect ──────────────>|  accept()
  |                             |  register user_id → socket
  |                             |
  |   (other user sends DM)     |
  |<── new_message event ───────|  push(user_id, payload)
  |                             |
  |   (group member sends msg)  |
  |<── new_group_message ───────|  push_to_many(member_ids, payload)
  |                             |
  |── "ping" text frame ───────>|  (keeps connection alive, ignored)
  |                             |
  |── disconnect ───────────────|  deregister user_id
```

> **Note:** The WebSocket connection is in-memory only. If the server restarts, clients must reconnect. Offline users do not receive missed events — use the REST history endpoints on reconnect to fetch missed messages.

---

---

## DM Flow Diagram

```
User A                    Server                    User B
  |                          |                          |
  |── POST /conversations ──>|  create conv (requested) |
  |                          |── WS: new_message ──────>|
  |<── 201 conv{requested} ──|                          |
  |                          |                          |
  |── POST .../messages ────>|  A can still send        |
  |                          |── WS: new_message ──────>|
  |                          |                          |
  |   (B sees request)       |                          |
  |                          |<── POST .../accept ──────|
  |                          |  status → active         |
  |                          |── 200 conv{active} ─────>|
  |                          |                          |
  |── POST .../messages ────>|  both can send freely    |
  |                          |── WS: new_message ──────>|
  |                          |                          |
  |                          |<── POST .../messages ────|
  |<── WS: new_message ──────|                          |
```

---

---

## Error Reference

All errors follow this shape:

```json
{
  "detail": "This conversation is blocked."
}
```

| HTTP Status | Meaning | Common Causes |
|-------------|---------|---------------|
| `400` | Bad Request | Self-chat attempt (`participant_id == user_id`) |
| `403` | Forbidden | Not a member; conversation blocked; send gate (non-initiator in requested state); member frozen; chat_perm=admins_only and not admin |
| `404` | Not Found | Conversation or group does not exist |
| `409` | Conflict | Accept/decline on an already-active or blocked conversation |
| `422` | Unprocessable Entity | Missing required fields, invalid UUID, invalid `message_type` |

---

## Quick Reference — All Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/chat/{user_id}/conversations` | List all DM conversations |
| `POST` | `/api/v1/chat/{user_id}/conversations` | Open DM + send first message |
| `GET` | `/api/v1/chat/{user_id}/conversations/{conv_id}/messages` | DM message history (paginated) |
| `POST` | `/api/v1/chat/{user_id}/conversations/{conv_id}/messages` | Send DM message |
| `POST` | `/api/v1/chat/{user_id}/conversations/{conv_id}/accept` | Accept chat request |
| `POST` | `/api/v1/chat/{user_id}/conversations/{conv_id}/decline` | Decline chat request |
| `POST` | `/api/v1/chat/{user_id}/conversations/{conv_id}/read` | Mark conversation read |
| `GET` | `/api/v1/chat/{user_id}/groups/{group_id}/messages` | Group message history (paginated) |
| `POST` | `/api/v1/chat/{user_id}/groups/{group_id}/messages` | Send group message |
| `WS` | `/ws/chat/{user_id}` | Real-time push connection |

---

## Testing Checklist

### Setup
- [ ] Server running: `uvicorn main:app --reload` (from `/backend`)
- [ ] DB migrated: `alembic upgrade head`
- [ ] At least two users with profiles exist — note their UUIDs from the `users` table
- [ ] At least one group created via the Groups API (for group chat tests)
- [ ] `pip install websocket-client` (for WebSocket tests)

### DM — Happy Path
- [ ] **POST /conversations** with User A → User B — expect `201`, `status: "requested"`, `created: true`
- [ ] Same call again — expect `201`, `created: false` (idempotent)
- [ ] **User A sends follow-up** while `requested` — expect `201`
- [ ] **User B tries to send** while `requested` — expect `403`
- [ ] **POST .../accept** as User B — expect `200`, `status: "active"`
- [ ] **Both users can now send** — expect `201` for each
- [ ] **GET .../messages** — expect `200`, messages newest first
- [ ] Cursor pagination — pass `oldest_timestamp` as `before`, expect older messages
- [ ] **POST .../read** — expect `200`; subsequent list should show `unread_count: 0`

### DM — Decline Flow
- [ ] Open new DM A → C, **POST .../decline** as C — expect `200`, `status: "blocked"`
- [ ] User A tries to send — expect `403`
- [ ] **Accept again** on blocked conv — expect `409`

### DM — Error Cases
- [ ] Self-chat (`participant_id == user_id`) — expect `400`
- [ ] Get messages for conv not a member of — expect `403`
- [ ] Decline non-existent conv — expect `404`
- [ ] Accept already-active conv — expect `409`

### Group Chat — Happy Path
- [ ] **POST /groups/{group_id}/messages** as a member — expect `201`, `context_type: "group"`
- [ ] **GET /groups/{group_id}/messages** as a member — expect `200`, messages list
- [ ] Send `image` message with `media_url` — expect `201`
- [ ] Send `audio` message with `media_url` — expect `201`
- [ ] Send with `reply_to_id` — expect `201`, verify `reply_to_id` in response
- [ ] Cursor pagination with `before=` — expect correct older page

### Group Chat — Error Cases
- [ ] Non-member sends — expect `403`
- [ ] Non-member reads — expect `403`
- [ ] Non-existent group — expect `404`

### WebSocket
- [ ] Connect `WS /ws/chat/{user_id}` — connection established
- [ ] User A opens DM with User B — User B's socket receives `new_message` event
- [ ] User A sends group message — all online members receive `new_group_message` event
- [ ] Disconnect and reconnect — use REST history to fetch missed messages

### Runner Scripts
```bash
cd backend

# DM smoke test
python scripts/test_chat.py

# Group chat smoke test (auto-joins members)
python scripts/test_group_chat.py
```

---

## Integration Notes for Frontend

### DM Chat

1. **Inbox screen** — Call `GET /conversations` on mount. Poll or reconnect WebSocket on focus.

2. **Opening a chat** — Call `POST /conversations`. If `created: true`, show the conversation as `requested` with a pending banner. If `created: false`, navigate to the existing conversation.

3. **Request state UI** — When `status == "requested"`:
   - Initiator: show "Waiting for {name} to accept your chat request"
   - Receiver: show an **Accept / Decline** action bar

4. **Sending messages** — Call `POST .../messages`. On `403` with status `requested`, remind the user the other party hasn't accepted yet.

5. **Real-time messages** — Listen on the WebSocket. On `new_message` event, append to the local message list for `conversation_id`.

6. **Message history** — Load the latest 50 on open. Pull older messages by passing `oldest_timestamp` as `before` when the user scrolls to the top.

7. **Unread badges** — Use `unread_count` from the conversation list. Call `POST .../read` when the user opens the conversation.

### Group Chat

1. **Group screen** — Load history via `GET /groups/{group_id}/messages` on mount.

2. **Sending** — Call `POST /groups/{group_id}/messages`. Handle `403` with a toast: "You are not allowed to send messages in this group" (frozen or admins-only).

3. **Real-time messages** — The same WebSocket connection handles group push. On `new_group_message` event, check `data.group_id` and append to the correct group chat screen.

4. **Reconnect strategy** — On WebSocket disconnect, reconnect with exponential backoff. On reconnect, call `GET /groups/{group_id}/messages` (without `before`) to fetch any missed messages.

### Message Types — Rendering Guide

| `message_type` | Render as |
|----------------|-----------|
| `text` | Plain text bubble |
| `image` | Image thumbnail + optional caption (`body`) |
| `video` | Video player + optional caption |
| `audio` | Audio waveform / play button |
| `document` | File icon + filename from `media_url` |
| `location` | Map pin with optional label (`body`) |
| `system` | Centered system label (e.g. "Rajesh accepted your request") |

### Reply-to UI

When `reply_to_id` is not null, fetch the referenced message from your local cache (it will already be in the history) and show it as a quoted bubble above the message body.
