#!/usr/bin/env python3
"""Find available meeting times with attendees.

Usage:
    python3 find_time.py --with "alice@example.com" --date 2026-04-17 --duration 30
    python3 find_time.py --with "alice@example.com,bob@example.com" --date 2026-04-17
    python3 find_time.py --with "alice@example.com" --start "2026-04-17T09:00" --end "2026-04-17T17:00"
    python3 find_time.py --json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Find available meeting times")
    parser.add_argument("--with", dest="attendees", required=True, help="Comma-separated attendee emails")
    parser.add_argument("--date", help="Date to search (YYYY-MM-DD, default: tomorrow)")
    parser.add_argument("--start", help="Start of search window (YYYY-MM-DDTHH:MM)")
    parser.add_argument("--end", help="End of search window (YYYY-MM-DDTHH:MM)")
    parser.add_argument("--duration", type=int, default=30, help="Meeting duration in minutes (default: 30)")
    parser.add_argument("--max", type=int, default=5, help="Max suggestions (default: 5)")
    parser.add_argument("--tz", default="America/Los_Angeles", help="Timezone")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    attendees = [a.strip() for a in args.attendees.split(",") if a.strip()]
    date = args.date or datetime.now().strftime("%Y-%m-%d")

    if args.start and args.end:
        start_dt, end_dt = args.start, args.end
    else:
        start_dt = f"{date}T08:00:00"
        end_dt = f"{date}T18:00:00"

    client = GraphClient()
    result = client.post("/me/findMeetingTimes", {
        "attendees": [{"emailAddress": {"address": a}, "type": "required"} for a in attendees],
        "timeConstraint": {
            "timeslots": [{
                "start": {"dateTime": start_dt, "timeZone": args.tz},
                "end": {"dateTime": end_dt, "timeZone": args.tz},
            }]
        },
        "meetingDuration": f"PT{args.duration}M",
        "maxCandidates": args.max,
    })

    suggestions = []
    for slot in result.get("meetingTimeSuggestions", []):
        start = slot.get("meetingTimeSlot", {}).get("start", {}).get("dateTime", "")[:16]
        end = slot.get("meetingTimeSlot", {}).get("end", {}).get("dateTime", "")[:16]
        confidence = slot.get("confidence", 0)
        suggestions.append({"start": start, "end": end, "confidence": confidence})

    if args.json:
        print(json.dumps({"total": len(suggestions), "suggestions": suggestions}, indent=2))
    else:
        if not suggestions:
            print(f"No available slots found on {date} for {', '.join(attendees)}.")
            return
        print(f"Available {args.duration}min slots on {date} with {', '.join(attendees)}:\n")
        for s in suggestions:
            print(f"  {s['start']} - {s['end']}")


if __name__ == "__main__":
    main()
