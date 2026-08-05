# 23 — Notifications

**Stated plainly, per this handbook's validation rules: this app does not send push notifications, and has no in-app notification inbox either.** This chapter documents exactly what does exist (a place to store a device token, and nothing that reads it back out), and what currently substitutes for notifications in practice.

## What exists: one column, one write path, nothing else

`User.fcm_token` (`app/modules/profile/models.py:26`) stores an **FCM (Firebase Cloud Messaging) registration token** — a per-device identifier a mobile client obtains from Firebase and would need to hand to a backend so that backend can later ask Firebase to push a notification to that specific device. The entire pipeline around this column, in full:

- `PATCH /profile/user/fcm-token` (`profile/router.py:135-143`), JWT-protected, accepting `{"fcm_token": "..."}`
- `update_fcm_token(db, user_id, fcm_token)` (`profile/service.py:129-133`) — writes the value straight onto the `User` row, no validation of the token's shape or format

That's the whole pipeline. This handbook grepped every file in `app/` for `firebase_admin.messaging` (the Firebase Admin SDK's actual push-sending API), and for `fcm`/`push_notification`/`send_notification` more broadly — the only matches anywhere are the four files that store and write this one column. **Nothing in this codebase ever reads `User.fcm_token` back out, and nothing ever calls Firebase (or any other push provider) to actually send a notification.** [Background Jobs](18_Background_Jobs.md)'s complete, verified list of every scheduled job has nothing notification-related either. There is also no in-app notification feed/inbox model of any kind (no `Notification` table, no `/notifications` endpoint) — this isn't a case of "push is missing but there's an in-app bell icon instead"; neither exists.

`firebase_admin` (the SDK) *is* used elsewhere in this app — but only its `auth` module, for phone-OTP verification during [Authentication](14_Authentication.md). That's a completely separate Firebase capability (identity verification) from Cloud Messaging (push delivery); importing one doesn't imply the other is wired up, and it isn't.

## What functions as a substitute today

The one thing in this app that behaves *like* a notification — something happened, tell the relevant user right now — is [Event Flows](20_Event_Flows.md)'s Socket.IO push system: `new_message`, `message_request_accepted`, `new_group_deal`, and the rest. The crucial difference from a real push notification: these only reach a client that currently holds an **open, live socket connection** to this app's own server. If the app is closed, backgrounded on a device that has killed the connection, or the user simply isn't looking at it, nothing arrives — there's no OS-level notification banner, no lock-screen alert, nothing queued for delivery on next open beyond whatever a REST endpoint would show anyway if the client asks (e.g. an unread-message count from the database, computed on demand rather than pushed).

## What would need to be built for real push notifications

Not a recommendation to build this — just a factual note on the gap, since "the token is already being collected, so sending must already work" is an easy, wrong assumption for a new engineer to make. Turning the collected `fcm_token` into working push notifications would need, at minimum: a call to the Firebase Admin SDK's `messaging.send(...)` (or `send_multicast`) at each of the moments [Event Flows](20_Event_Flows.md) already identifies as "something worth telling a user about," a decision on whether that call happens inline (blocking the request) or via `BackgroundTasks`/a scheduled job (consistent with the patterns [Background Jobs](18_Background_Jobs.md) and [Event Flows](20_Event_Flows.md) already establish elsewhere in this app), and handling for the token going stale (Firebase itself will report a token as invalid once an app uninstalls or a token rotates — nothing in this schema currently distinguishes a fresh token from a dead one, since nothing has ever tried to use one).

---
**Previous:** [22 — Search](22_Search.md) · **Next:** [24 — Configuration](24_Configuration.md)
