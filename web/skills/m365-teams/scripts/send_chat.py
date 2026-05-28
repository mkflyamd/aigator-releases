#!/usr/bin/env python3
"""Send a Teams chat message to anyone by email.

Constructs the chat thread ID from user IDs, bypassing the Chat.Create
scope limitation. Works with just ChatMessage.Send + People.Read scopes.

Usage:
    python3 send_chat.py --to "alice@example.com" --message "Hello!"
    python3 send_chat.py --chat-id <chat_id> --message "Hello!"
    python3 send_chat.py --to "alice@example.com" --message "<b>Bold</b>" --html
    python3 send_chat.py --chat-id "48:notes" --message "reminder"
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def find_user_id(client: GraphClient, email: str) -> str:
    """Look up a user's ID by email using People API."""
    result = client.get("/me/people", params={"$search": f'"{ email}"', "$top": "5"})
    for person in result.get("value", []):
        for addr in person.get("scoredEmailAddresses", []):
            if addr.get("address", "").lower() == email.lower():
                uid = person.get("id", "")
                if uid:
                    return uid
    for person in result.get("value", []):
        uid = person.get("id", "")
        if uid:
            return uid
    return ""


def construct_chat_id(my_id: str, their_id: str) -> str:
    """Construct 1:1 chat thread ID from two user IDs (sorted alphabetically)."""
    ids = sorted([my_id, their_id])
    return f"19:{ids[0]}_{ids[1]}@unq.gbl.spaces"


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a Teams chat message")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--to", help="Recipient email address")
    group.add_argument("--chat-id", help="Existing chat ID (e.g., 48:notes for self)")
    parser.add_argument("--message", "-m", required=True, help="Message content")
    parser.add_argument("--html", action="store_true", help="Send as HTML content")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    content_type = "html" if args.html else "text"

    chat_id = args.chat_id
    if args.to:
        me = client.get("/me")
        my_id = me.get("id", "")
        if not my_id:
            print("ERROR: Could not get your user ID", file=sys.stderr)
            sys.exit(1)
        their_id = find_user_id(client, args.to)
        if not their_id:
            print(f"ERROR: Could not find user '{args.to}'", file=sys.stderr)
            sys.exit(1)
        chat_id = construct_chat_id(my_id, their_id)

    result = client.post(f"/chats/{chat_id}/messages", {
        "body": {"contentType": content_type, "content": args.message},
    })

    if args.json:
        print(json.dumps({"message": "sent", "chat_id": chat_id,
                           "message_id": result.get("id", "")}, indent=2))
    else:
        print(f"Message sent to {args.to or chat_id}")


if __name__ == "__main__":
    main()
