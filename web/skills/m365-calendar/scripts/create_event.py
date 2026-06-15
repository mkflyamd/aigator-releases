#!/usr/bin/env python3
"""Create a calendar event / meeting.

Usage:
    python3 create_event.py --subject "Design Review" \
        --start "2026-04-17T14:00:00" --end "2026-04-17T14:30:00" \
        --attendees "alice@example.com,bob@example.com" --teams

    python3 create_event.py --subject "Lunch" \
        --start "2026-04-17T12:00:00" --end "2026-04-17T13:00:00"
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a calendar event")
    parser.add_argument("--subject", required=True, help="Event subject")
    parser.add_argument("--start", required=True, help="Start time (YYYY-MM-DDTHH:MM:SS)")
    parser.add_argument("--end", required=True, help="End time (YYYY-MM-DDTHH:MM:SS)")
    parser.add_argument("--attendees", help="Comma-separated attendee emails")
    parser.add_argument("--body", help="Event body/description")
    parser.add_argument("--location", help="Location name")
    parser.add_argument("--teams", action="store_true", help="Add Teams meeting link")
    parser.add_argument("--tz", default="America/Los_Angeles", help="Timezone")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    event = {
        "subject": args.subject,
        "start": {"dateTime": args.start, "timeZone": args.tz},
        "end": {"dateTime": args.end, "timeZone": args.tz},
    }

    if args.attendees:
        event["attendees"] = [
            {"emailAddress": {"address": a.strip()}, "type": "required"}
            for a in args.attendees.split(",") if a.strip()
        ]

    if args.body:
        event["body"] = {"contentType": "text", "content": args.body}

    if args.location:
        event["location"] = {"displayName": args.location}

    if args.teams:
        event["isOnlineMeeting"] = True
        event["onlineMeetingProvider"] = "teamsForBusiness"

    client = GraphClient()
    result = client.post("/me/events", event)

    output = {
        "message": "Event created",
        "subject": result.get("subject", ""),
        "start": result.get("start", {}).get("dateTime", "")[:16],
        "end": result.get("end", {}).get("dateTime", "")[:16],
        "id": result.get("id", ""),
        "teams_link": result.get("onlineMeeting", {}).get("joinUrl", "") if result.get("onlineMeeting") else "",
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"Event created: {output['subject']}")
        print(f"  {output['start']} - {output['end']}")
        if output["teams_link"]:
            print(f"  Teams: {output['teams_link']}")


if __name__ == "__main__":
    main()
