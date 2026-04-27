#!/usr/bin/env python3
"""
Interactive WebSocket chat tester for Vanijyaa backend.

Run in two separate terminals:
  Terminal 1 (User 1): python test_chat.py
  Terminal 2 (User 2): python test_chat.py

Flow:
  User 1: /new <user2_uuid>   → type first message → sends chat request
  User 2: /list               → see incoming request + conversation ID
  User 2: /accept <conv_id>   → accepts the request
  Both:   just type & press Enter to chat in real-time

Requirements: pip install websockets requests
"""

import asyncio
import json
import sys
import threading
import time
from datetime import datetime
from uuid import UUID

import requests

try:
    import websockets
except ImportError:
    print("Missing dependency. Run:  pip install websockets requests")
    sys.exit(1)

BASE_URL = "http://localhost:8000"
WS_URL   = "ws://localhost:8000"

# ── ANSI colours ──────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
BLUE   = "\033[94m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RED    = "\033[91m"
GRAY   = "\033[90m"
WHITE  = "\033[97m"

# ── Shared state (set from main thread, read from WS thread) ──────────────────
state = {
    "user_id":  None,
    "conv_id":  None,
    "running":  True,
}


# ── Display helpers ───────────────────────────────────────────────────────────

def _ts():
    return datetime.now().strftime("%H:%M:%S")


def print_system(msg: str):
    print(f"\r{GRAY}[{_ts()}] {YELLOW}» {msg}{RESET}")
    _reprint_prompt()


def print_incoming(sender_name: str, body: str, ts: str = ""):
    print(f"\r{BLUE}{BOLD}{sender_name}{RESET}  {GRAY}{ts}{RESET}")
    print(f"  {WHITE}{body}{RESET}")
    _reprint_prompt()


def _reprint_prompt():
    print(f"{CYAN}> {RESET}", end="", flush=True)


# ── REST helpers ──────────────────────────────────────────────────────────────

def _get(path: str, **params):
    try:
        r = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, body: dict | None = None):
    try:
        r = requests.post(f"{BASE_URL}{path}", json=body or {}, timeout=30)
        try:
            data = r.json()
        except Exception:
            data = {}
        data["_http_status"] = r.status_code
        return data
    except Exception as e:
        return {"error": str(e)}


# ── Chat actions ──────────────────────────────────────────────────────────────

def list_conversations():
    uid = state["user_id"]
    resp = _get(f"/api/v1/chat/{uid}/conversations")
    convs = (resp.get("data") or {}).get("conversations", [])
    if not convs:
        print_system("No conversations found.")
        return
    print(f"\n{BOLD}Your conversations:{RESET}")
    for c in convs:
        status      = c["status"]
        participant = c["participant"].get("name") or c["participant"]["user_id"]
        last        = c.get("last_message")
        preview     = (last.get("body") or "")[:50] if last else ""
        colour      = GREEN if status == "active" else YELLOW
        print(f"  {colour}[{status.upper()}]{RESET}  {BOLD}{participant}{RESET}")
        print(f"    conv_id : {CYAN}{c['id']}{RESET}")
        if preview:
            print(f"    last msg: {GRAY}{preview}{RESET}")
    print()


def cmd_new(target_id: str):
    try:
        UUID(target_id)
    except ValueError:
        print_system("Invalid UUID.")
        return
    first_msg = input(f"{BOLD}First message to send: {RESET}").strip()
    if not first_msg:
        print_system("Message cannot be empty.")
        return
    resp = _post(
        f"/api/v1/chat/{state['user_id']}/conversations",
        {"participant_id": target_id, "message": first_msg},
    )
    http_status = resp.get("_http_status")
    data = resp.get("data") or {}
    conv = data.get("conversation", {})
    if conv.get("id"):
        state["conv_id"] = conv["id"]
        conv_status = conv.get("status", "?")
        print_system(
            f"Chat started! conv_id={CYAN}{conv['id']}{RESET}{YELLOW}"
            f"  status={conv_status}"
            f"  — tell User 2 to run /list then /accept {conv['id']}"
        )
    elif resp.get("error"):
        print_system(f"Network error: {resp['error']}")
    else:
        print_system(f"Failed (HTTP {http_status}): {resp.get('message', resp)}")


def cmd_accept(conv_id: str):
    resp = _post(f"/api/v1/chat/{state['user_id']}/conversations/{conv_id}/accept")
    http_status = resp.get("_http_status")
    data = resp.get("data") or {}
    conv = data.get("conversation", {})
    if conv.get("id"):
        state["conv_id"] = conv["id"]
        print_system(f"Accepted! Status is now {GREEN}{conv.get('status')}{RESET}{YELLOW}. You can start typing.")
    elif resp.get("error"):
        print_system(f"Network error: {resp['error']}")
    else:
        print_system(f"Failed (HTTP {http_status}): {resp.get('message', resp)}")


def _do_send(conv_id: str, body: str):
    resp = _post(
        f"/api/v1/chat/{state['user_id']}/conversations/{conv_id}/messages",
        {"body": body, "message_type": "text"},
    )
    status = resp.get("_http_status")
    if status == 201:
        return  # success — receiver sees it via WebSocket
    elif status == 403:
        print_system("Cannot send: conversation is still in 'requested' state. User 2 must /accept first.")
    elif resp.get("error"):
        print_system(f"Network error: {resp['error']}")
    else:
        print_system(f"Send failed (HTTP {status}): {resp.get('message', resp)}")


def cmd_send(body: str):
    conv_id = state["conv_id"]
    if not conv_id:
        print_system("No active conversation. Use /new <uuid> or /accept <conv_id> first.")
        return
    # Run in background so the input prompt stays responsive while DB round-trip completes
    threading.Thread(target=_do_send, args=(conv_id, body), daemon=True).start()


# ── WebSocket listener (background thread) ────────────────────────────────────

async def _ws_loop():
    uri = f"{WS_URL}/ws/chat/{state['user_id']}"
    print_system(f"Connecting WebSocket …  {GRAY}{uri}{RESET}{YELLOW}")
    try:
        async with websockets.connect(uri) as ws:
            print_system("WebSocket connected. Waiting for messages …")
            async for raw in ws:
                if not state["running"]:
                    break
                try:
                    payload = json.loads(raw)
                    event = payload.get("event")
                    data  = payload.get("data", {})

                    if event in ("new_message", "new_group_message"):
                        msg    = data.get("message", {})
                        sender = msg.get("sender", {})
                        name   = sender.get("name") or sender.get("user_id", "?")
                        body   = msg.get("body") or f"[{msg.get('message_type', 'media')}]"
                        sent   = msg.get("sent_at", "")
                        ts     = sent[11:16] if len(sent) > 15 else _ts()[:-3]

                        # Auto-capture conv_id if we don't have one yet (User 2 flow)
                        if not state["conv_id"] and data.get("conversation_id"):
                            state["conv_id"] = data["conversation_id"]
                            print_system(
                                f"New chat request received!"
                                f"  Run:  /accept {state['conv_id']}"
                            )

                        print_incoming(name, body, ts)

                except Exception as exc:
                    print_system(f"WS parse error: {exc}")

    except Exception as exc:
        print_system(f"WebSocket disconnected: {exc}")


def _ws_thread_main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_ws_loop())


# ── Help text ─────────────────────────────────────────────────────────────────

HELP = f"""
{BOLD}Commands{RESET}
  {CYAN}/list{RESET}                   List all your conversations
  {CYAN}/new  <user_uuid>{RESET}       Start a chat with another user   (User 1 flow)
  {CYAN}/accept <conv_uuid>{RESET}     Accept an incoming chat request  (User 2 flow)
  {CYAN}/use  <conv_uuid>{RESET}       Switch active conversation
  {CYAN}/conv{RESET}                   Show current conversation ID
  {CYAN}/help{RESET}                   Show this message
  {CYAN}/quit{RESET}                   Exit

  {GREEN}Just type and press Enter to send a message{RESET}
"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Header
    print(f"\n{BOLD}{CYAN}{'━'*55}{RESET}")
    print(f"{BOLD}{CYAN}   Vanijyaa · Interactive Chat Tester{RESET}")
    print(f"{BOLD}{CYAN}{'━'*55}{RESET}\n")

    # Identify user
    raw = input(f"{BOLD}Enter your User ID (UUID): {RESET}").strip()
    try:
        UUID(raw)
    except ValueError:
        print(f"{RED}Not a valid UUID. Exiting.{RESET}")
        sys.exit(1)

    state["user_id"] = raw
    print(f"\n{GREEN}Signed in as: {raw}{RESET}\n")

    # Start WS listener
    t = threading.Thread(target=_ws_thread_main, daemon=True)
    t.start()
    time.sleep(0.8)  # let WS connect before printing help

    print(HELP)

    # Interactive loop
    while state["running"]:
        try:
            line = input(f"{CYAN}> {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not line:
            continue

        if line == "/quit":
            break
        elif line == "/help":
            print(HELP)
        elif line == "/list":
            list_conversations()
        elif line == "/conv":
            if state["conv_id"]:
                print_system(f"Active conversation: {CYAN}{state['conv_id']}{RESET}{YELLOW}")
            else:
                print_system("No active conversation.")
        elif line.startswith("/new "):
            cmd_new(line[5:].strip())
        elif line.startswith("/accept "):
            cmd_accept(line[8:].strip())
        elif line.startswith("/use "):
            cid = line[5:].strip()
            state["conv_id"] = cid
            print_system(f"Switched to: {CYAN}{cid}{RESET}{YELLOW}")
        elif line.startswith("/"):
            print_system("Unknown command. Type /help.")
        else:
            cmd_send(line)

    state["running"] = False
    print(f"\n{GRAY}Bye!{RESET}\n")


if __name__ == "__main__":
    main()
