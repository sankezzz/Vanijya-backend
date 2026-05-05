# Auth Module — Complete Flow Documentation

## Overview

The auth system uses **three token types** and a **session table** in the database.
Every authenticated API call is validated in two steps: first the JWT is checked
(fast, no DB), then the session row in `user_sessions` is checked (ensures
revocation works even within the JWT's lifetime).

---

## The Three Token Types

### 1. Onboarding Token
| Property | Value |
|----------|-------|
| Format | JWT (signed HS256) |
| Expiry | **15 minutes** |
| Stored in DB? | No |
| Used for | Only the two profile-creation steps |

**JWT payload:**
```json
{
  "sub": "user-uuid",
  "phone_number": "9876543210",
  "country_code": "+91",
  "token_type": "onboarding",
  "exp": 1234567890
}
```

This token is given to a user who just verified their phone but hasn't created
a profile yet. It carries the phone number and country code so the profile
creation endpoints know who to register. Once both `/profile/user` and
`/profile/` are called successfully, this token is no longer needed and the
user receives a proper access + refresh token pair.

---

### 2. Access Token
| Property | Value |
|----------|-------|
| Format | JWT (signed HS256) |
| Expiry | **1 hour** (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES` in `.env`) |
| Stored in DB? | No — only its `jti` (session ID) is stored as the `user_sessions.id` column |
| Used for | Every protected API call via `Authorization: Bearer <token>` |

**JWT payload:**
```json
{
  "sub": "user-uuid",
  "jti": "session-uuid",
  "type": "access",
  "exp": 1234567890
}
```

- `sub` — the user's UUID, used to identify who is making the request
- `jti` (JWT ID) — the UUID of the `user_sessions` row this token belongs to.
  This is the key to revocation: if you set `user_sessions.is_active = false`,
  all access tokens that reference that session immediately stop working.
- `exp` — standard JWT expiry timestamp

---

### 3. Refresh Token
| Property | Value |
|----------|-------|
| Format | Opaque random string (NOT a JWT) |
| Expiry | **30 days** (configurable via `REFRESH_TOKEN_EXPIRE_DAYS` in `.env`) |
| Stored in DB? | SHA-256 hash stored in `user_sessions.refresh_token_hash` |
| Used for | Only `POST /auth/refresh` to get a new access token |

The refresh token is a random 48-byte URL-safe string generated with Python's
`secrets.token_urlsafe(48)`. It is **never stored as plain text** — only its
SHA-256 hash is saved. When the client presents it, the server hashes the
incoming value and compares it to the stored hash.

---

## The Session Row (`user_sessions` table)

Every time a user logs in, a new row is created here:

```
user_sessions
─────────────────────────────────────────────────────────────
id               UUID  ← this is the `jti` inside the access JWT
user_id          UUID  ← FK to users.id
refresh_token_hash  VARCHAR(64)  ← SHA-256 of the raw refresh token
expires_at       TIMESTAMPTZ  ← 30 days from login (session hard deadline)
is_active        BOOLEAN  ← set to false on logout or force-revoke
device_info      VARCHAR(255)  ← optional ("iPhone 15 / iOS 17")
ip_address       VARCHAR(45)   ← optional, logged at login
created_at       TIMESTAMPTZ
last_used_at     TIMESTAMPTZ  ← updated on every token refresh
```

One user can have **multiple active sessions** (multiple devices). Logout only
kills the session for the current device. `revoke_all_sessions()` exists for
force-logout-all-devices scenarios.

---

## How Access Token Validation Works (Every API Request)

When a protected endpoint is called:

```
Client                          Server
──────                          ──────
Authorization: Bearer <jwt>
                           ──►  1. Decode JWT
                                   - Verify HS256 signature with JWT_SECRET_KEY
                                   - Check `exp` claim — reject if expired
                                   - Check `type == "access"` claim
                                   - Extract `sub` (user_id) and `jti` (session_id)

                           ──►  2. DB lookup
                                   SELECT * FROM user_sessions
                                   WHERE id = <session_id>
                                   AND is_active = true

                                   - Not found or is_active=false → 401 "Session revoked"
                                   - expires_at < now → 401 "Session expired"

                           ──►  3. Return user_id to the route handler
```

This two-layer check means:
- A stolen access token becomes useless the moment you call `POST /auth/logout`
  (sets `is_active = false`) even if the JWT itself hasn't expired yet
- A token still in its 1-hour window but belonging to a revoked session is rejected

---

## Token Refresh Flow (After Access Token Expires)

The access token lasts **1 hour**. When it expires, the client gets a `401`
response from any API. It should then:

```
Client                               Server
──────                               ──────
POST /auth/refresh
Body: { "refresh_token": "<raw>" }
                                ──►  1. SHA-256 hash the incoming refresh token
                                     2. SELECT * FROM user_sessions
                                        WHERE refresh_token_hash = <hash>
                                        AND is_active = true
                                     3. Check expires_at — reject if past 30 days
                                     4. Generate new access_token (new 1-hr JWT,
                                        same session_id in jti)
                                     5. Generate new refresh_token (new random string)
                                     6. UPDATE user_sessions
                                        SET refresh_token_hash = SHA256(new_refresh)
                                            last_used_at = now
                                     7. Return new access_token + refresh_token
◄──
Store new tokens, retry original request
```

**Why is the refresh token also rotated (replaced)?**
Each refresh produces a brand-new refresh token. If someone steals your old
refresh token and tries to use it after you've already refreshed, the stored
hash will no longer match — their attempt will fail with 401.

---

## Complete User Journeys

### Journey 1: New User (First Time Ever)

```
[Phone]                    [App / Client]              [Backend]
  │                              │                          │
  │  Firebase sends OTP via SMS  │                          │
  │◄─────────────────────────────│                          │
  │  User types OTP into app     │                          │
  │─────────────────────────────►│                          │
  │                              │  Firebase verifies OTP   │
  │                              │  ──────────────────────► │ (Firebase SDK, not our server)
  │                              │◄────────────────────────  │
  │                              │  firebase_id_token        │
  │                              │                          │
  │                              │  POST /auth/firebase-verify
  │                              │  { firebase_id_token }   │
  │                              │─────────────────────────►│
  │                              │                          │  Verify token with Firebase Admin SDK
  │                              │                          │  Extract phone + country_code
  │                              │                          │  No user found in DB
  │                              │                          │  Create onboarding_token (15 min JWT)
  │                              │◄─────────────────────────│
  │                              │  { is_new_user: true,    │
  │                              │    onboarding_token }    │
  │                              │                          │
  │        [Screen: Name/Role]   │                          │
  │                              │  POST /profile/user      │
  │                              │  Authorization: Bearer <onboarding_token>
  │                              │─────────────────────────►│
  │                              │                          │  Decode onboarding token
  │                              │                          │  Extract user_id, phone, country_code
  │                              │                          │  INSERT INTO users (id, phone, country_code)
  │                              │◄─────────────────────────│
  │                              │  { user_id }             │
  │                              │                          │
  │  [Screen: City/Commodities]  │                          │
  │                              │  POST /profile/          │
  │                              │  Authorization: Bearer <onboarding_token>
  │                              │  Body: { name, role_id, city, commodities... }
  │                              │─────────────────────────►│
  │                              │                          │  Decode onboarding token
  │                              │                          │  INSERT INTO profile (...)
  │                              │                          │  Build 11-dim embedding vector
  │                              │                          │  CREATE SESSION in user_sessions
  │                              │                          │    - id = new UUID (this is the jti)
  │                              │                          │    - refresh_token_hash = SHA256(random)
  │                              │                          │    - expires_at = now + 30 days
  │                              │                          │  Create access_token JWT (1 hour)
  │                              │◄─────────────────────────│
  │                              │  { profile,              │
  │                              │    access_token,         │
  │                              │    refresh_token,        │
  │                              │    expires_in: 3600 }    │
  │                              │                          │
  │                              │  *** Store both tokens ***
  │                              │  Onboarding complete — user is in the app
```

---

### Journey 2: Returning User (Login After App Reinstall / New Phone)

```
[App / Client]                       [Backend]
      │                                   │
      │  POST /auth/firebase-verify       │
      │  { firebase_id_token }            │
      │──────────────────────────────────►│
      │                                   │  Verify Firebase token
      │                                   │  User + profile found in DB
      │                                   │  CREATE SESSION in user_sessions
      │                                   │    - New session row (old sessions untouched)
      │                                   │  Issue new access_token + refresh_token
      │◄──────────────────────────────────│
      │  { is_new_user: false,            │
      │    access_token,                  │
      │    refresh_token,                 │
      │    expires_in: 3600,              │
      │    user_id, profile_id }          │
      │                                   │
      │  *** Store both tokens ***
      │  User is in the app
```

---

### Journey 3: Using the App (Every API Call)

```
[App / Client]                       [Backend]
      │                                   │
      │  GET /feed  (or any protected API)│
      │  Authorization: Bearer <access_token>
      │──────────────────────────────────►│
      │                                   │  Decode JWT → user_id + session_id
      │                                   │  Query user_sessions by session_id
      │                                   │  is_active=true? expires_at > now?
      │                                   │  → Yes: proceed, return user_id
      │◄──────────────────────────────────│
      │  200 + response data              │
```

---

### Journey 4: Access Token Expired (After 1 Hour)

```
[App / Client]                       [Backend]
      │                                   │
      │  GET /feed                        │
      │  Authorization: Bearer <expired_access_token>
      │──────────────────────────────────►│
      │                                   │  JWT decode fails: exp in the past
      │◄──────────────────────────────────│
      │  401 "Access token has expired"   │
      │                                   │
      │  POST /auth/refresh               │
      │  { "refresh_token": "<raw>" }     │
      │──────────────────────────────────►│
      │                                   │  Hash incoming token
      │                                   │  Find session by hash
      │                                   │  Session still valid (30 days)
      │                                   │  Generate new access_token (1 hour)
      │                                   │  Generate new refresh_token (random)
      │                                   │  Update session.refresh_token_hash
      │◄──────────────────────────────────│
      │  { access_token, refresh_token }  │
      │                                   │
      │  *** Replace stored tokens ***    │
      │                                   │
      │  Retry GET /feed                  │
      │  Authorization: Bearer <new_access_token>
      │──────────────────────────────────►│
      │◄──────────────────────────────────│
      │  200 + response data              │
```

---

### Journey 5: Logout

```
[App / Client]                       [Backend]
      │                                   │
      │  POST /auth/logout                │
      │  Authorization: Bearer <access_token>
      │──────────────────────────────────►│
      │                                   │  Decode access_token → session_id (jti)
      │                                   │  UPDATE user_sessions
      │                                   │    SET is_active = false
      │                                   │    WHERE id = session_id
      │◄──────────────────────────────────│
      │  200 "Logged out successfully"    │
      │                                   │
      │  *** Delete stored tokens ***     │
      │                                   │
      │  Any future call with old token   │
      │──────────────────────────────────►│
      │                                   │  JWT decodes fine (still in 1-hr window)
      │                                   │  DB lookup: is_active = false
      │◄──────────────────────────────────│
      │  401 "Session has been revoked"   │
```

---

## Why Not Just Use the JWT's `exp` for Everything?

A standard JWT approach would be: "token expires, user is logged out". The
problem is that JWTs cannot be revoked before their expiry. If someone's phone
is stolen or a token is compromised, you have no way to invalidate it until the
1-hour `exp` passes.

By tying every JWT to a `user_sessions` row via `jti`, you can:
- **Logout immediately** — set `is_active = false`, the token stops working in
  the same second even if it was issued 5 minutes ago
- **Force-logout all devices** — set all of a user's sessions to inactive
- **See active sessions** — query `user_sessions` to know what devices/IPs are
  logged in
- **Expire sessions by age** — the `expires_at` column is a hard cutoff
  independent of how many times the access token is refreshed

The refresh token (30 days) is the "stay logged in" mechanism. The access token
(1 hour) is what actually gates API calls.

---

## API Reference

### `POST /auth/firebase-verify`
**No auth required.**

Request:
```json
{
  "firebase_id_token": "<token from Firebase SDK>",
  "device_info": "iPhone 15 / iOS 17"
}
```

Response (new user):
```json
{
  "is_new_user": true,
  "onboarding_token": "<15-min JWT>",
  "token_type": "bearer"
}
```

Response (returning user):
```json
{
  "is_new_user": false,
  "access_token": "<1-hr JWT>",
  "refresh_token": "<opaque 30-day token>",
  "expires_in": 3600,
  "user_id": "uuid",
  "profile_id": 42,
  "token_type": "bearer"
}
```

---

### `POST /profile/user`
**Requires: `Authorization: Bearer <onboarding_token>`**

Creates the `users` DB row. Called once, right after receiving `onboarding_token`.

---

### `POST /profile/`
**Requires: `Authorization: Bearer <onboarding_token>`**

Creates the profile. This is the **last step of onboarding** and returns the
first real token pair:
```json
{
  "profile": { ... },
  "access_token": "<1-hr JWT>",
  "refresh_token": "<opaque 30-day token>",
  "token_type": "bearer",
  "expires_in": 3600
}
```

---

### `POST /auth/refresh`
**No auth required.** (The refresh token IS the credential.)

Request:
```json
{
  "refresh_token": "<stored raw refresh token>"
}
```

Response:
```json
{
  "access_token": "<new 1-hr JWT>",
  "refresh_token": "<new rotated refresh token>",
  "token_type": "bearer",
  "expires_in": 3600
}
```

---

### `POST /auth/logout`
**Requires: `Authorization: Bearer <access_token>`**

Request body can be empty `{}`. Revokes the session identified by the token's
`jti` claim. Returns `200` even if the token is already expired (idempotent).

---

## Environment Variables

Add these to your `.env`:

```env
JWT_SECRET_KEY=<long random string>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=30
```
