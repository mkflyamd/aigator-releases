#!/usr/bin/env python3
"""Delete / cancel a calendar event.

Usage:
    python3 delete_event.py --event-id <event_id>
    python3 delete_event.py --event-id <event_id> --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete a calendar event")
    parser.add_argument("--event-id", required=True, help="Event ID (from list_events.py --json)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    client.delete(f"/me/events/{args.event_id}")

    if args.json:
        print(json.dumps({"message": "Event deleted", "id": args.event_id}, indent=2))
    else:
        print(f"Event deleted: {args.event_id}")


if __name__ == "__main__":
    main()
