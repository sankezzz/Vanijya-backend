# Profile Module — Developer Guide & Test Reference

A complete reference for the onboarding flow, profile creation, and profile management APIs.

Base URL (local): `https://vanijyaa-backend.onrender.com`

---

## Table of Contents

1. [Local Setup](#1-local-setup)
2. [How Auth Works](#2-how-auth-works)
3. [Seed the Database](#3-seed-the-database)
4. [Get an Onboarding Token](#4-get-an-onboarding-token)
5. [API Quick Reference](#5-api-quick-reference)
6. [Onboarding Flow](#6-onboarding-flow)
7. [Profile APIs](#7-profile-apis)
8. [Database Schema](#8-database-schema)
9. [Error Reference](#9-error-reference)

---

## 1. Local Setup

**Start the server:**
```bash
uvicorn main:app --reload
```

Server runs at `http://localhost:8000`.
Swagger UI at `http://localhost:8000/docs` — use this to test all endpoints interactively.

---

## 2. How Auth Works

The profile module uses **two different auth mechanisms** depending on the stage:

| Stage | Endpoints | Auth mechanism |
|---|---|---|
| **Onboarding (new users)** | `POST /profile/user` and `POST /profile/` | `Authorization: Bearer <onboarding_token>` |
| **Post-registration** | `GET /me`, `PATCH /`, `DELETE /`, `GET /{id}` | Query parameter `?user_id=<uuid>` — no token |

### Onboarding token
- Issued by `POST /auth/firebase-verify` for new users
- JWT signed with HS256, expires in 15 minutes
- Contains: `user_id`, `phone_number`, `country_code`, `token_type: "onboarding"`

### Post-registration auth
- After registration, pass `user_id` as a query parameter — no Bearer token required
- Example: `GET /profile/me?user_id=c37a3257-dc3f-43be-9fb0-33cf918b11ff`

---

## 3. Seed the Database

Profiles require valid `role_id`, `commodity` IDs, and `interest` IDs. These must exist in the lookup tables first.

**Run once:**
```bash
python scripts/seed.py
```

**Current seed data:**

### Roles
| Name | ID |
|---|---|
| `trader` | `1` |
| `broker` | `2` |
| `exporter` | `3` |

### Commodities
| Name | ID |
|---|---|
| `rice` | `1` |
| `cotton` | `2` |
| `sugar` | `3` |

### Interests
| Name | ID |
|---|---|
| `connections` | `1` |
| `leads` | `2` |
| `news` | `3` |

---

## 4. Get an Onboarding Token

Auth uses **Firebase Phone OTP**. The client obtains a Firebase ID token after verifying the OTP, then sends it to the backend.

### Step 1 — Verify Firebase token (get onboarding token)

```bash
curl -X POST http://localhost:8000/auth/firebase-verify \
  -H "Content-Type: application/json" \
  -d '{ "firebase_id_token": "<FIREBASE_ID_TOKEN>" }'
```

**Response — new user:**
```json
{
    "success": true,
    "data": {
        "onboarding_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "token_type": "bearer",
        "expires_in": 900
    }
}
```

**Response — returning user (profile already exists):**
```json
{
    "success": true,
    "data": {
        "user_id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff"
    }
}
```

Copy the `onboarding_token` — use it for `POST /profile/user` and `POST /profile/`.  
Returning users get `user_id` directly and skip the onboarding steps.

---

**To use in Swagger UI (`/docs`):**
1. Open `http://localhost:8000/docs`
2. Click **Authorize** (top right, lock icon)
3. Paste the onboarding token in the `Value` field — click **Authorize**
4. All requests now send `Authorization: Bearer <token>` automatically

**To use in Postman / curl:**
```
Authorization: Bearer <onboarding_token>
```

---

## 5. API Quick Reference

| Method | Endpoint | Auth | What it does |
|---|---|---|---|
| `POST` | `/profile/user` | Bearer onboarding token | Create the user row (step 1) |
| `POST` | `/profile/` | Bearer onboarding token | Create profile (step 2) |
| `GET` | `/profile/me` | `?user_id=<uuid>` | Fetch your own profile |
| `PATCH` | `/profile/` | `?user_id=<uuid>` | Update your profile |
| `DELETE` | `/profile/` | `?user_id=<uuid>` | Delete your profile |
| `GET` | `/profile/my-posts` | `?user_id=<uuid>` | My posts (paginated) |
| `GET` | `/profile/saved` | `?user_id=<uuid>` | My saved posts (paginated) |
| `GET` | `/profile/{profile_id}` | None (public) | Public view of any profile |

---

## 6. Onboarding Flow

Profile creation is a **two-step process** — both steps use the **onboarding token**.

```
Step 1: POST /profile/user    ← creates the User row (phone, country_code)
Step 2: POST /profile/        ← creates Profile + commodities + interests
```

Both steps must use the **same onboarding token** issued in Section 4.

---

### Step 1 — `POST /profile/user`

Creates the `users` row. Must be called before creating a profile.

**Auth:** `Authorization: Bearer <ONBOARDING_TOKEN>`  
**Body:** None — phone number and country code are read from the token.

**Example (curl):**
```bash
curl -X POST http://localhost:8000/profile/user \
  -H "Authorization: Bearer <ONBOARDING_TOKEN>"
```

**Success `201`:**
```json
{
    "success": true,
    "message": "User created successfully",
    "data": {
        "id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
        "phone_number": "9876543210",
        "country_code": "+91",
        "created_at": "2026-04-16T10:00:00.000000"
    }
}
```

**Error `409`** — user already exists:
```json
{ "detail": "Phone number already registered" }
```

---

### Step 2 — `POST /profile/`

Creates the profile. Call immediately after Step 1 with the same token.

**Auth:** `Authorization: Bearer <ONBOARDING_TOKEN>`  
**Content-Type:** `application/json`

**Request body:**
```json
{
    "name": "Ravi Traders",
    "role_id": 1,
    "commodities": [1, 2],
    "interests": [1, 2],
    "quantity_min": 100,
    "quantity_max": 500,
    "business_name": "Ravi Agro Pvt Ltd",
    "latitude": 19.076,
    "longitude": 72.877
}
```

**Field reference:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | Display name |
| `role_id` | int | Yes | `1`=trader, `2`=broker, `3`=exporter |
| `commodities` | int[] | Yes | At least one — `1`=rice, `2`=cotton, `3`=sugar |
| `interests` | int[] | Yes | At least one — `1`=connections, `2`=leads, `3`=news |
| `quantity_min` | float | Yes | Minimum trade quantity in MT |
| `quantity_max` | float | Yes | Must be ≥ `quantity_min` |
| `business_name` | string | No | Optional business name |
| `latitude` | float | Yes | Business location latitude |
| `longitude` | float | Yes | Business location longitude |

**Example (curl):**
```bash
curl -X POST http://localhost:8000/profile/ \
  -H "Authorization: Bearer <ONBOARDING_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Ravi Traders",
    "role_id": 1,
    "commodities": [1, 2],
    "interests": [1, 2],
    "quantity_min": 100,
    "quantity_max": 500,
    "business_name": "Ravi Agro Pvt Ltd",
    "latitude": 19.076,
    "longitude": 72.877
  }'
```

**Success `200`:**
```json
{
    "success": true,
    "message": "Profile created successfully",
    "data": {
        "id": 1,
        "name": "Ravi Traders",
        "role_id": 1,
        "commodities": [
            { "id": 1, "name": "rice" },
            { "id": 2, "name": "cotton" }
        ],
        "interests": [
            { "id": 1, "name": "connections" },
            { "id": 2, "name": "leads" }
        ],
        "is_verified": false,
        "is_user_verified": false,
        "is_business_verified": false,
        "followers_count": 0,
        "business_name": "Ravi Agro Pvt Ltd",
        "latitude": 19.076,
        "longitude": 72.877
    }
}
```

**Error `409`** — profile already exists:
```json
{ "detail": "Profile already exists for this user" }
```

**Error `400`** — invalid IDs or quantity mismatch:
```json
{ "detail": "Invalid commodity_ids: 99" }
```

---

## 7. Profile APIs

All endpoints in this section authenticate via the `user_id` **query parameter** — no Bearer token.

---

### `GET /profile/me`

Fetch your own full profile.

**Example:**
```bash
curl "http://localhost:8000/profile/me?user_id=c37a3257-dc3f-43be-9fb0-33cf918b11ff"
```

**Success `200`:**
```json
{
    "success": true,
    "message": "Profile fetched successfully",
    "data": {
        "id": 1,
        "name": "Ravi Traders",
        "role_id": 1,
        "commodities": [
            { "id": 1, "name": "rice" }
        ],
        "interests": [
            { "id": 1, "name": "connections" }
        ],
        "is_verified": false,
        "is_user_verified": false,
        "is_business_verified": false,
        "followers_count": 0,
        "business_name": "Ravi Agro Pvt Ltd",
        "latitude": 19.076,
        "longitude": 72.877
    }
}
```

---

### `PATCH /profile/`

Update your profile. All fields are optional — only send what you want to change.

**Request body:**
```json
{
    "name": "Ravi Global Traders",
    "commodities": [3],
    "interests": [1, 3],
    "quantity_min": 200,
    "quantity_max": 1000,
    "business_name": "Ravi Agro International",
    "latitude": 18.520,
    "longitude": 73.856
}
```

**Commodity / interest update behaviour:**  
Pass the complete new list. Items not in the list are removed. Items already present are kept. New items are added.

**Example — update just the name:**
```bash
curl -X PATCH "http://localhost:8000/profile/?user_id=c37a3257-dc3f-43be-9fb0-33cf918b11ff" \
  -H "Content-Type: application/json" \
  -d '{ "name": "Ravi Global Traders" }'
```

**Success `200`:**
```json
{
    "success": true,
    "message": "Profile updated successfully",
    "data": { "..." }
}
```

---

### `DELETE /profile/`

Permanently delete your profile (hard delete — not reversible).

```bash
curl -X DELETE "http://localhost:8000/profile/?user_id=c37a3257-dc3f-43be-9fb0-33cf918b11ff"
```

**Success `200`:**
```json
{
    "success": true,
    "message": "Profile deleted successfully",
    "data": null
}
```

---

### `GET /profile/{profile_id}` — Public View

View any user's public profile. **No auth required.**

**URL parameter:**

| Param | Type | Description |
|---|---|---|
| `profile_id` | int | The profile's integer ID (from your `/me` response) |

**Example:**
```bash
curl http://localhost:8000/profile/1
```

**Success `200`:**
```json
{
    "success": true,
    "message": "Profile fetched successfully",
    "data": {
        "id": 1,
        "name": "Ravi Traders",
        "role_id": 1,
        "is_verified": false,
        "commodities": [
            { "id": 1, "name": "rice" }
        ],
        "business_name": "Ravi Agro Pvt Ltd",
        "latitude": 19.076,
        "longitude": 72.877,
        "posts_count": 0
    }
}
```

---

### `GET /profile/my-posts`

Fetch your own posts (paginated).

**Query parameters:**

| Param | Default | Description |
|---|---|---|
| `user_id` | required | Your user UUID |
| `limit` | 20 | Max results to return |
| `offset` | 0 | Skip N results (for pagination) |

```bash
curl "http://localhost:8000/profile/my-posts?user_id=c37a3257-dc3f-43be-9fb0-33cf918b11ff&limit=10&offset=0"
```

---

### `GET /profile/saved`

Fetch your saved posts (paginated). Same query parameters as `my-posts`.

---

## 8. Database Schema

Tables created by the migration (`alembic upgrade head`):

```
users                  — auth identity (phone + country_code, fcm_token, access_token)
roles                  — trader / broker / exporter
profile                — main profile (linked 1:1 to user)
commodities            — rice / cotton / sugar / ...
profile_commodities    — profile ↔ commodity (many-to-many)
interests              — connections / leads / news
profile_interests      — profile ↔ interest (many-to-many)
document_types         — GST, PAN, APEDA ...
role_document_requirements — which docs each role needs
profile_documents      — uploaded docs per profile (with verification status)
user_embeddings        — IS vector for matching (built on profile create/update)
posts                  — stub table (post module coming soon)
```

Run migrations:
```bash
alembic upgrade head
```

Check current migration state:
```bash
alembic current
```

---

## 9. Error Reference

| Status | When it happens |
|---|---|
| `400` | Invalid IDs (role/commodity/interest not in DB), `quantity_min > quantity_max` |
| `401` | Missing, expired, or wrong token type (onboarding token required but not provided) |
| `404` | User or profile not found |
| `409` | User already registered, or profile already exists for this user |
| `422` | Missing required field or wrong data type (FastAPI validation) |

All errors follow FastAPI's default shape:
```json
{
    "detail": "Human-readable description of what went wrong."
}
```

---

## Full Test Sequence (copy-paste order)

```bash
# 1. Start server
uvicorn main:app --reload

# 2. Seed lookup tables (run once)
python scripts/seed.py

# 3. Verify Firebase ID token — get onboarding_token from response
curl -X POST http://localhost:8000/auth/firebase-verify \
  -H "Content-Type: application/json" \
  -d '{ "firebase_id_token": "<FIREBASE_ID_TOKEN>" }'

# 4. Create user row (paste ONBOARDING_TOKEN from step 3)
curl -X POST http://localhost:8000/profile/user \
  -H "Authorization: Bearer <ONBOARDING_TOKEN>"

# 5. Create profile (same ONBOARDING_TOKEN from step 3)
curl -X POST http://localhost:8000/profile/ \
  -H "Authorization: Bearer <ONBOARDING_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Ravi Traders",
    "role_id": 1,
    "commodities": [1, 2],
    "interests": [1, 2],
    "quantity_min": 100,
    "quantity_max": 500,
    "business_name": "Ravi Agro",
    "latitude": 19.076,
    "longitude": 72.877
  }'

# 6. Fetch your profile (replace USER_ID with the UUID from step 4 response)
curl "http://localhost:8000/profile/me?user_id=<USER_ID>"

# 7. Update name only
curl -X PATCH "http://localhost:8000/profile/?user_id=<USER_ID>" \
  -H "Content-Type: application/json" \
  -d '{ "name": "Ravi Global Traders" }'

# 8. Public profile view (replace PROFILE_ID with the int id from step 6 response)
curl http://localhost:8000/profile/<PROFILE_ID>

# 9. Delete
curl -X DELETE "http://localhost:8000/profile/?user_id=<USER_ID>"
```
