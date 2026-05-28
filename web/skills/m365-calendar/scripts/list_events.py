#!/usr/bin/env python3
"""List calendar events for a date range.

Usage:
    python3 list_events.py                  # Today's events
    python3 list_events.py --date 2026-04-17  # Specific date
    python3 list_events.py --days 7          # Next 7 days
    python3 list_events.py --start 2026-04-16 --end 2026-04-18
    python3 list_events.py --json
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="List calendar events")
    parser.add_argument("--date", help="Specific date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, help="Number of days from today")
    parser.add_argument("--start", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="End date (YYYY-MM-DD)")
    parser.add_argument("--count", type=int, default=50, help="Max events (default: 50)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if args.date:
        start = datetime.strptime(args.date, "%Y-%m-%d")
        end = start + timedelta(days=1)
    elif args.days:
        start = today
        end = today + timedelta(days=args.days)
    elif args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d")
        end = datetime.strptime(args.end, "%Y-%m-%d") + timedelta(days=1)
    else:
        start = today
        end = today + timedelta(days=1)

    client = GraphClient()
    data = client.get("/me/calendarView", params={
        "startDateTime": start.strftime("%Y-%m-%dT00:00:00Z"),
        "endDateTime": end.strftime("%Y-%m-%dT23:59:59Z"),
        "$top": str(args.count),
        "$orderby": "start/dateTime",
        "$select": "subject,start,end,isAllDay,organizer,location,onlineMeetingUrl,attendees,isCancelled",
    })

    events = [{
        "subject": e.get("subject", "(no subject)"),
        "start": e.get("start", {}).get("dateTime", "")[:16],
        "end": e.get("end", {}).get("dateTime", "")[:16],
        "all_day": e.get("isAllDay", False),
        "organizer": e.get("organizer", {}).get("emailAddress", {}).get("name", ""),
        "location": e.get("location", {}).get("displayName", ""),
        "teams_link": e.get("onlineMeetingUrl", ""),
        "id": e.get("id", ""),
    } for e in data.get("value", []) if not e.get("isCancelled")]

    if args.json:
        print(json.dumps({"total": len(events), "events": events}, indent=2))
    else:
        label = args.date or (f"{args.days} days" if args.days else "today")
        if not events:
            print(f"No events for {label}.")
            return
        print(f"Events for {label} ({len(events)}):\n")
        for e in events:
            if e["all_day"]:
                print(f"  [All Day] {e['subject']}")
            else:
                print(f"  {e['start']} - {e['end']}")
                print(f"    {e['subject']}")
            if e["location"]:
                print(f"    Location: {e['location']}")
            print(f"    Organizer: {e['organizer']}")
            print()


if __name__ == "__main__":
    main()
