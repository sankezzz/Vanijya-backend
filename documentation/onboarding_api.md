# Vanijyaa — Onboarding API Reference

**Base URL:** `https://vanijyaa-backend.onrender.com`

**Interactive docs (Swagger):** `https://vanijyaa-backend.onrender.com/docs`

---

## How Auth Works

Onboarding uses a short-lived **onboarding token** to carry your phone identity through the registration steps. Once the profile is created, **no token is needed for any API** — you identify yourself by passing your `user_id` directly in the URL or as a query parameter.

| Token | Used for | How to get it |
|---|---|---|
| `onboarding_token` | `POST /profile/user` and `POST /profile/` only | Returned by `POST /auth/verify-otp` — **new users only** |

The onboarding token goes in the `Authorization` header during registration:
```
Authorization: Bearer <onboarding_token>
```

> After registration, **no token is required**. All APIs accept `user_id` in the URL or as `?user_id=`.

---

## Step 1 — Send OTP

```
POST /auth/send-otp
Content-Type: application/json
```

**Request body:**
```json
{
    "phone_number": "9876543210",
    "country_code": "+91"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `phone_number` | string | Yes | Digits only, no country prefix |
| `country_code` | string | Yes | E.g. `"+91"` |

**Success `200`:**
```json
{
    "success": true,
    "message": "OTP sent successfully"
}
```

> In **dev mode** (`DEV_MODE=true`), no SMS is sent — the 6-digit OTP is printed to the server terminal.

---

## Step 2 — Verify OTP

```
POST /auth/verify-otp
Content-Type: application/json
```

**Request body:**
```json
{
    "phone_number": "9876543210",
    "country_code": "+91",
    "otp_code": "482931"
}
```

**Success `200` — new user:**
```json
{
    "success": true,
    "message": "OTP verified. Use the onboarding token to complete registration.",
    "data": {
        "is_new_user": true,
        "onboarding_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "user_id": null,
        "token_type": "bearer"
    }
}
```

**Success `200` — returning user (profile already exists):**
```json
{
    "success": true,
    "message": "Welcome back. Use your saved user_id to continue.",
    "data": {
        "is_new_user": false,
        "onboarding_token": null,
        "user_id": "c37a3257-dc3f-43be-9fb0-33cf918b11ff",
        "token_type": "bearer"
    }
}
```

**Frontend logic:**
```
if is_new_user == true  → proceed to Steps 3 & 4 using the onboarding_token
if is_new_user == false → skip onboarding — save the returned user_id to local storage
```

> The `onboarding_token` expires in **15 minutes**.

---

## Step 3 — Create User Row

```
POST /profile/user
Authorization: Bearer <onboarding_token>
```

No request body — phone number and country code are read directly from the token.

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

**Save the `id`** — this is the user's UUID. Store it locally and pass it in all subsequent API calls.

**Error `409`** — phone number already registered:
```json
{ "detail": "Phone number already registered" }
```

---

## Step 4 — Create Profile

```
POST /profile/
Authorization: Bearer <onboarding_token>
Content-Type: application/json
```

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
    "longitude": 72.877,
    "experience": 5
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | Display name |
| `role_id` | int | Yes | See Roles table below |
| `commodities` | int[] | Yes | At least one — see Commodities table |
| `interests` | int[] | Yes | At least one — see Interests table |
| `quantity_min` | float | Yes | Min trade quantity in MT |
| `quantity_max` | float | Yes | Must be ≥ `quantity_min` |
| `business_name` | string | No | Optional |
| `latitude` | float | Yes | Location latitude |
| `longitude` | float | Yes | Location longitude |
| `experience` | int | No | Years of experience |

**Lookup IDs (pre-seeded integers):**

Roles:
| Name | ID |
|---|---|
| `trader` | `1` |
| `broker` | `2` |
| `exporter` | `3` |

Commodities:
| Name | ID |
|---|---|
| `rice` | `1` |
| `cotton` | `2` |
| `sugar` | `3` |

Interests:
| Name | ID |
|---|---|
| `connections` | `1` |
| `leads` | `2` |
| `news` | `3` |

**Success `200`:**
```json
{
    "success": true,
    "message": "Profile created successfully",
    "data": {
        "profile": {
            "id": 1,
            "name": "Ravi Traders",
            "role_id": 1,
            "commodities": [
                { "id": 1, "name": "rice" },
                { "id": 2, "name": "cotton" }
            ],
            "is_verified": false,
            "followers_count": 0,
            "business_name": "Ravi Agro Pvt Ltd",
            "latitude": 19.076,
            "longitude": 72.877,
            "experience": 5
        }
    }
}
```

**Error `409`** — profile already exists:
```json
{ "detail": "Profile already exists for this user" }
```

---

## Step 5 — Save FCM Token (Push Notifications)

Call this immediately after Step 4 to register the device for push notifications. No token needed — pass `user_id` as a query parameter.

```
PATCH /profile/user/fcm-token?user_id=<user_uuid>
Content-Type: application/json
```

**Request body:**
```json
{
    "fcm_token": "<firebase-device-token>"
}
```

**Success `200`:**
```json
{
    "success": true,
    "message": "FCM token updated",
    "data": null
}
```

> Call this again whenever the Firebase device token rotates.

---

## Complete Onboarding Sequence

```
NEW USER
────────
POST /auth/send-otp                                     → OTP sent to phone
POST /auth/verify-otp                                   → { is_new_user: true, onboarding_token }
POST /profile/user          ← onboarding_token          → user row created  ← SAVE this UUID
POST /profile/              ← onboarding_token          → profile created
PATCH /profile/user/fcm-token?user_id=<uuid>            → device registered for push

RETURNING USER
──────────────
POST /auth/send-otp                                     → OTP sent to phone
POST /auth/verify-otp                                   → { is_new_user: false, user_id: "<uuid>" }
                                                           ↑ skip all steps — save user_id to local storage
```

---

## Onboarding Endpoint Summary

| Method | Endpoint | Token Required | What it does |
|---|---|---|---|
| `POST` | `/auth/send-otp` | None | Request OTP via SMS |
| `POST` | `/auth/verify-otp` | None | Verify OTP → onboarding_token (new) or user_id (returning) |
| `POST` | `/profile/user` | `onboarding_token` | Create user row — returns `user_id` UUID |
| `POST` | `/profile/` | `onboarding_token` | Create profile |
| `PATCH` | `/profile/user/fcm-token?user_id=` | None | Register device for push notifications |
