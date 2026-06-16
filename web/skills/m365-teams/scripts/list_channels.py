#!/usr/bin/env python3
"""List channels in a Teams team.

Usage:
    python3 list_channels.py --team-id <team_id>
    python3 list_channels.py --team-id <team_id> --json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from graph_client import GraphClient


def main() -> None:
    parser = argparse.ArgumentParser(description="List channels in a team")
    parser.add_argument("--team-id", required=True, help="Team ID (from list_teams.py)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = GraphClient()
    data = client.get(f"/teams/{args.team_id}/channels")
    channels = [{"id": c["id"], "name": c.get("displayName", ""),
                 "description": c.get("description", "")}
                for c in data.get("value", [])]

    if args.json:
        print(json.dumps({"total": len(channels), "channels": channels}, indent=2))
    else:
        if not channels:
            print("No channels found.")
            return
        print(f"Channels ({len(channels)}):\n")
        for c in channels:
            desc = f" - {c['description']}" if c["description"] else ""
            print(f"  {c['name']}{desc}")
            print(f"    ID: {c['id']}")


if __name__ == "__main__":
    main()
