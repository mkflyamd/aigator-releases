#!/usr/bin/env python3
"""Check free/busy status for one or more users.

Usage:
    python3 free_busy.py --users "alice@example.com" --date 2026-04-17
    python3 free_busy.py --users "alice@example.com,bob@example.com" --date 2026-04-17
    python3 free_busy.py --users "alice@example.com" --start "2026-04-17T09:00" --end "2026-04-17T17:00"
    python3 free_busy.py --users "alice@example.com" --date 2026-04-17 --json
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient

STATUS_MAP = {"0": "Free", "1": "Tentative", "2": "Busy", "3": "OOF", "4": "Working Elsewhere"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check free/busy status")
    parser.add_argument("--users", required=True, help="Comma-separated email addresses")
    parser.add_argument("--date", help="Date to check (YYYY-MM-DD, default: today)")
    parser.add_argument("--start", help="Start time (YYYY-MM-DDTHH:MM)")
    parser.add_argument("--end", help="End time (YYYY-MM-DDTHH:MM)")
    parser.add_argument("--interval", type=int, default=30, help="Interval in minutes (default: 30)")
    parser.add_argument("--tz", default="America/Los_Angeles", help="Timezone")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    users = [u.strip() for u in args.users.split(",") if u.strip()]
    date = args.date or datetime.now().strftime("%Y-%m-%d")

    if args.start and args.end:
        start_dt, end_dt = args.start, args.end
    else:
        start_dt = f"{date}T08:00:00"
        end_dt = f"{date}T18:00:00"

    client = GraphClient()
    result = client.post("/me/calendar/getSchedule", {
        "schedules": users,
        "startTime": {"dateTime": start_dt, "timeZone": args.tz},
        "endTime": {"dateTime": end_dt, "timeZone": args.tz},
        "availabilityViewInterval": args.interval,
    })

    schedules = []
    for s in result.get("value", []):
        view = s.get("availabilityView", "")
        items = s.get("scheduleItems", [])
        schedules.append({
            "user": s.get("scheduleId", ""),
            "availability_view": view,
            "busy_slots": [{"subject": i.get("subject",""), "status": i.get("status",""),
                            "start": i.get("start",{}).get("dateTime","")[:16],
                            "end": i.get("end",{}).get("dateTime","")[:16]}
                           for i in items],
        })

    if args.json:
        print(json.dumps({"schedules": schedules}, indent=2))
    else:
        print(f"Free/Busy for {date} ({args.tz}):\n")
        print(f"  Legend: 0=Free, 1=Tentative, 2=Busy, 3=OOF, 4=Working Elsewhere\n")
        for s in schedules:
            print(f"  {s['user']}")
            print(f"    {s['availability_view']}")
            for slot in s["busy_slots"]:
                print(f"    {slot['start']} - {slot['end']} [{slot['status']}] {slot['subject']}")
            print()


if __name__ == "__main__":
    main()
