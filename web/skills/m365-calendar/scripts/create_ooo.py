#!/usr/bin/env python3
"""Create an Out of Office calendar event.

Creates an all-day OOF event on your calendar and sends informational
invites to recipients that show as FREE on their calendars (no response
requested, no time blocked).

Implementation:
  1. Create event with showAs="free", responseRequested=false, attendees
     as "optional" — recipients get the event without time being blocked
  2. PATCH the organizer's event to showAs="oof" — your calendar shows OOF

Usage:
    python3 create_ooo.py --date 2026-04-21 --notify "kush.jain@example.com"
    python3 create_ooo.py --start 2026-04-21 --end 2026-04-25 --notify "alice@example.com,bob@example.com"
    python3 create_ooo.py --date 2026-04-21 --notify "team@example.com" --subject "OOF: Trung - PTO"
    python3 create_ooo.py --date 2026-04-21 --notify "kush.jain@example.com" --body "On PTO, reach out to Alice for urgent issues."
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an Out of Office event")
    parser.add_argument("--date", help="Single OOF date (YYYY-MM-DD)")
    parser.add_argument("--start", help="Start date for multi-day OOF (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date for multi-day OOF (YYYY-MM-DD, inclusive)")
    parser.add_argument("--notify", required=True, help="Comma-separated emails to notify (shows as FREE on their calendar)")
    parser.add_argument("--subject", help="Custom subject (default: 'OOF: <your name>')")
    parser.add_argument("--body", help="Optional message body (e.g., backup contact info)")
    parser.add_argument("--tz", default="America/Los_Angeles", help="Timezone (default: America/Los_Angeles)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if not args.date and not (args.start and args.end):
        print("ERROR: Provide --date for single day, or --start and --end for a range.", file=sys.stderr)
        sys.exit(1)

    if args.date:
        start_date = args.date
        end_date = args.date
    else:
        start_date = args.start
        end_date = args.end

    client = GraphClient()

    # Get organizer name for default subject
    if not args.subject:
        me = client.get("/me", params={"$select": "displayName"})
        name = me.get("displayName", "")
        subject = f"OOF: {name}"
    else:
        subject = args.subject

    recipients = [a.strip() for a in args.notify.split(",") if a.strip()]

    # All-day events require end = next day at midnight
    from datetime import datetime, timedelta
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    end_midnight = end_dt.strftime("%Y-%m-%dT00:00:00")

    # Step 1: Create event with showAs="free" so recipients don't get blocked
    event = {
        "subject": subject,
        "isAllDay": True,
        "start": {"dateTime": f"{start_date}T00:00:00", "timeZone": args.tz},
        "end": {"dateTime": end_midnight, "timeZone": args.tz},
        "showAs": "free",  # Recipients see FREE (not blocked)
        "responseRequested": False,  # No accept/decline prompt
        "isReminderOn": False,
        "attendees": [
            {
                "emailAddress": {"address": addr},
                "type": "optional",  # Informational — doesn't require attendance
            }
            for addr in recipients
        ],
    }

    if args.body:
        event["body"] = {"contentType": "text", "content": args.body}

    result = client.post("/me/events", event)
    event_id = result.get("id", "")

    if not event_id:
        print("ERROR: Failed to create event.", file=sys.stderr)
        sys.exit(1)

    # Step 2: Patch YOUR copy to showAs="oof" so your calendar shows OOF
    patch_url = f"https://graph.microsoft.com/v1.0/me/events/{event_id}"
    patch_data = json.dumps({"showAs": "oof"}).encode()
    headers = client._headers()
    req = urllib.request.Request(patch_url, data=patch_data, headers=headers, method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        print(f"WARNING: Event created but failed to set OOF status ({e.code}). "
              f"Your calendar may show 'free' instead of 'oof'.", file=sys.stderr)

    date_label = start_date if start_date == end_date else f"{start_date} to {end_date}"

    output = {
        "message": "OOF event created",
        "subject": subject,
        "dates": date_label,
        "your_calendar": "Out of Office",
        "recipients_calendar": "Free (informational)",
        "notified": recipients,
        "id": event_id,
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"OOF event created: {subject}")
        print(f"  Dates: {date_label}")
        print(f"  Your calendar: Out of Office")
        print(f"  Recipients ({len(recipients)}): {', '.join(recipients)}")
        print(f"    Their calendar: Free (informational, no response requested)")


if __name__ == "__main__":
    main()
