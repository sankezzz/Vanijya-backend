# Vanijyaa — Sharing API Documentation

> **Added:** 2026-04-27
> **Module:** `app/modules/deeplink/`
> **Also modified:** `app/modules/chat/presentation/schemas.py`

---

## Overview

Two sharing flows are supported:

| Flow | Description |
|------|-------------|
| **External share** | Generate a `vanijyaa://` deep link + share text to send outside the app (WhatsApp, Telegram, SMS, etc.) |
| **In-app share** | Send a post / news article / user profile as a message inside an existing DM or group chat |

---

## External Share Endpoints

Base prefix: `/share`

All three endpoints are **public** (no auth required — anyone with the ID can generate the link).

---

### GET `/share/post/{post_id}`

Generate a shareable deep link for a post.

**Path parameter**

| Param | Type | Description |
|-------|------|-------------|
| `post_id` | `int` | ID of the post |

**Response `200`**

```json
{
  "success": true,
  "message": "Share link generated",
  "data": {
    "deep_link": "vanijyaa://post/42",
    "share_text": "Sanket Suryawanshi shared a post on Vanijyaa\n\nCotton prices expected to rise...\n\nOpen in app: vanijyaa://post/42\nDownload Vanijyaa: https://play.google.com/...",
    "title": "Post by Sanket Suryawanshi",
    "description": "Cotton prices expected to rise 12% — Market Update",
    "image_url": "https://cdn.supabase.io/..."
  }
}
```

**Errors**

| Code | Reason |
|------|--------|
| `404` | Post not found |

---

### GET `/share/news/{article_id}`

Generate a shareable deep link for a news article.

**Path parameter**

| Param | Type | Description |
|-------|------|-------------|
| `article_id` | `UUID` (string) | UUID of the news article |

**Response `200`**

```json
{
  "success": true,
  "message": "Share link generated",
  "data": {
    "deep_link": "vanijyaa://news/550e8400-e29b-41d4-a716-446655440000",
    "share_text": "Wheat export ban lifted by government\n\nIndia lifts the ban on wheat exports after...\n\nOpen in Vanijyaa: vanijyaa://news/550e8400-...\nDownload Vanijyaa: https://play.google.com/...",
    "title": "Wheat export ban lifted by government",
    "description": "India lifts the ban on wheat exports after...",
    "image_url": "https://cdn.source.com/image.jpg"
  }
}
```

**Errors**

| Code | Reason |
|------|--------|
| `400` | Invalid UUID format for `article_id` |
| `404` | Article not found |

---

### GET `/share/user/{profile_id}`

Generate a shareable deep link for a user profile.

**Path parameter**

| Param | Type | Description |
|-------|------|-------------|
| `profile_id` | `int` | Profile ID of the user |

**Response `200`**

```json
{
  "success": true,
  "message": "Share link generated",
  "data": {
    "deep_link": "vanijyaa://user/5",
    "share_text": "Connect with Sanket Suryawanshi on Vanijyaa\n\nShri Balaji Global · Pune\n\nOpen in app: vanijyaa://user/5\nDownload Vanijyaa: https://play.google.com/...",
    "title": "Sanket Suryawanshi",
    "description": "Shri Balaji Global · Pune",
    "image_url": "https://cdn.supabase.io/avatars/5.jpg"
  }
}
```

**Errors**

| Code | Reason |
|------|--------|
| `404` | Profile not found |

---

## Response Schema — `ShareLinkResponse`

All three endpoints return the same shape:

| Field | Type | Description |
|-------|------|-------------|
| `deep_link` | `string` | `vanijyaa://post/{id}` — pass to `Share.share()` or handle as incoming link |
| `share_text` | `string` | Full ready-to-send message including deep link + Play Store URL |
| `title` | `string` | Display title for the shared item |
| `description` | `string \| null` | Short description / caption (max 120 chars) |
| `image_url` | `string \| null` | Thumbnail URL, if available |

---

## In-App Share to Chat / Group

No new endpoints were added for in-app sharing. The existing send-message endpoints are used with a new `message_type` value.

**File changed:** `app/modules/chat/presentation/schemas.py`
**Change:** Added `post`, `news`, `user` to the allowed `message_type` pattern in both `SendMessageRequest` and `GroupMessageRequest`.

---

### Share to a DM

**`POST /api/v1/chat/{user_id}/conversations/{conv_id}/messages`**

```json
{
  "message_type": "post",
  "media_metadata": { "post_id": 42 },
  "body": "Check this out!"
}
```

---

### Share to a Group

**`POST /api/v1/chat/{user_id}/groups/{group_id}/messages`**

```json
{
  "message_type": "post",
  "media_metadata": { "post_id": 42 },
  "body": "Relevant for everyone here"
}
```

---

### Supported `message_type` values for sharing

| `message_type` | `media_metadata` key | ID type | Navigates to |
|----------------|----------------------|---------|--------------|
| `"post"` | `post_id` | `int` | Post detail screen |
| `"news"` | `article_id` | `UUID string` | News article screen |
| `"user"` | `profile_id` | `int` | User profile screen |

The `body` field is optional in all cases — use it to add a caption to the shared item.

---

## Deep Link URI Scheme — Summary

| Content | URI |
|---------|-----|
| Post | `vanijyaa://post/{post_id}` |
| News article | `vanijyaa://news/{article_id}` |
| User profile | `vanijyaa://user/{profile_id}` |

The `vanijyaa://` scheme must be registered in the Flutter app:
- **Android:** `<data android:scheme="vanijyaa" />` in `AndroidManifest.xml`
- **iOS:** `CFBundleURLSchemes` entry in `Info.plist`
- **Handler:** `app_links` package, `uriLinkStream` + `getInitialLink()`

---

## Flutter — Share Button Flow

```
User taps Share on a post
    ↓
Call GET /share/post/{post_id}
    ↓
Use share_text from response
    ↓
Share.share(shareText)   ← share_plus package
```

## Flutter — In-App Share Flow

```
User taps "Share to Chat / Group"
    ↓
Show conversation / group picker
    ↓
POST /chat/{userId}/conversations/{convId}/messages
  { message_type: "post", media_metadata: { post_id: 42 } }
    ↓
In chat bubble: when message_type == "post"
  → fetch GET /posts/{post_id}
  → render PostCard widget
  → tap navigates to post screen
```

---

## Files Added / Modified

| File | Change |
|------|--------|
| `app/modules/deeplink/__init__.py` | New module (empty) |
| `app/modules/deeplink/schemas.py` | `ShareLinkResponse` Pydantic schema |
| `app/modules/deeplink/service.py` | Business logic — fetch preview data, build deep link + share text |
| `app/modules/deeplink/router.py` | Three GET endpoints under `/share/` prefix |
| `main.py` | Registered `deeplink_router` |
| `app/modules/chat/presentation/schemas.py` | Added `post`, `news`, `user` to `message_type` regex in `SendMessageRequest` and `GroupMessageRequest` |
