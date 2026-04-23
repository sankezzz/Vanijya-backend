# Vanijyaa — Onboarding API Reference

**Base URL:** `https://vanijyaa-backend.onrender.com`

**Interactive docs (Swagger):** `https://vanijyaa-backend.onrender.com/docs`

---

## How Auth Works

OTP is sent **directly from the mobile app** via the Firebase Auth SDK — the backend is never involved in sending SMS. After the user enters the OTP, Firebase gives the app an **ID token**. The app sends that token to the backend, which verifies it and returns either an `onboarding_token` (new user) or the `user_id` (returning user).

| Token | Used for | How to get it |
|---|---|---|
| `onboarding_token` | `POST /profile/user` and `POST /profile/` only | Returned by `POST /auth/firebase-verify` — **new users only** |

The onboarding token goes in the `Authorization` header during registration:
```
Authorization: Bearer <onboarding_token>
```

> After registration, **no token is required**. All APIs accept `user_id` in the URL or as `?user_id=`.

---

## Step 1 — Send OTP (Client-side — Firebase SDK)

**No backend call needed.** The mobile app calls Firebase Auth directly:

```
// Flutter example
await FirebaseAuth.instance.verifyPhoneNumber(
  phoneNumber: '+919876543210',   // full E.164 format
  verificationCompleted: ...,
  verificationFailed: ...,
  codeSent: (verificationId, _) { ... },
  codeAutoRetrievalTimeout: ...,
);
```

Firebase sends the SMS. When the user enters the OTP, confirm it:

```
// Flutter example
final credential = PhoneAuthProvider.credential(
  verificationId: verificationId,
  smsCode: otpEnteredByUser,
);
final userCredential = await FirebaseAuth.instance.signInWithCredential(credential);
final idToken = await userCredential.user!.getIdToken();
// → send idToken to POST /auth/firebase-verify
```

---

## Step 2 — Verify with Backend

```
POST /auth/firebase-verify
Content-Type: application/json
```

**Request body:**
```json
{
    "firebase_id_token": "<id token returned by Firebase SDK after OTP confirmation>"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `firebase_id_token` | string | Yes | ID token from `user.getIdToken()` after phone sign-in |

**Success `200` — needs onboarding** (`is_new_user: true`):

Returned in three situations:
- Brand new phone number (never registered)
- Previously deleted account re-registering (account will be reactivated in Step 3)
- Existing user who never finished onboarding (no profile created yet)

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

**Error `401`** — invalid or expired Firebase token:
```json
{ "detail": "Invalid Firebase token: ..." }
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

> **Re-registration after account deletion:** If this user previously deleted their account, this call automatically reactivates it and wipes the old profile so they start fresh. The response looks identical to a new user — proceed to Step 4 normally.

**Error `409`** — active account already registered with this phone number:
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
    "city": "Mumbai",
    "state": "Maharashtra",
    "latitude": 19.076,
    "longitude": 72.877
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
| `city` | string | No | City name e.g. `"Mumbai"` |
| `state` | string | No | State name e.g. `"Maharashtra"` |
| `latitude` | float | Yes | Location latitude |
| `longitude` | float | Yes | Location longitude |

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
            "city": "Mumbai",
            "state": "Maharashtra",
            "latitude": 19.076,
            "longitude": 72.877,
            "avatar_url": null
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
[Client]  FirebaseAuth.verifyPhoneNumber(+91XXXXXXXXXX)   → Firebase sends SMS
[Client]  User enters OTP → signInWithCredential()         → get idToken
POST /auth/firebase-verify  { firebase_id_token }          → { is_new_user: true, onboarding_token }
POST /profile/user          ← onboarding_token             → user row created  ← SAVE this UUID
POST /profile/              ← onboarding_token             → profile created
PATCH /profile/user/fcm-token?user_id=<uuid>               → device registered for push

RETURNING USER
──────────────
[Client]  FirebaseAuth.verifyPhoneNumber(+91XXXXXXXXXX)   → Firebase sends SMS
[Client]  User enters OTP → signInWithCredential()         → get idToken
POST /auth/firebase-verify  { firebase_id_token }          → { is_new_user: false, user_id: "<uuid>" }
                                                              ↑ skip all steps — save user_id to local storage

RE-REGISTERING (previously deleted account)
────────────────────────────────────────────
[Client]  FirebaseAuth.verifyPhoneNumber(+91XXXXXXXXXX)   → Firebase sends SMS
[Client]  User enters OTP → signInWithCredential()         → get idToken
POST /auth/firebase-verify  { firebase_id_token }          → { is_new_user: true, onboarding_token }
                                                              ↑ same response as new user
POST /profile/user          ← onboarding_token             → account reactivated, old profile wiped ← SAVE UUID
POST /profile/              ← onboarding_token             → fresh profile created
PATCH /profile/user/fcm-token?user_id=<uuid>               → device registered for push
```

---

## Onboarding Endpoint Summary

| Method | Endpoint | Token Required | What it does |
|---|---|---|---|
| *(client SDK)* | Firebase `verifyPhoneNumber` | None | Firebase sends OTP SMS directly |
| `POST` | `/auth/firebase-verify` | None | Verify Firebase ID token → onboarding_token (new) or user_id (returning) |
| `POST` | `/profile/user` | `onboarding_token` | Create user row — returns `user_id` UUID |
| `POST` | `/profile/` | `onboarding_token` | Create profile |
| `PATCH` | `/profile/user/fcm-token?user_id=` | None | Register device for push notifications |
