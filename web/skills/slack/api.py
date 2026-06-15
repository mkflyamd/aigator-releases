"""Slack API client wrapper."""
import sys
from pathlib import Path

def get_slack_client():
    sys.path.insert(0, str(Path(__file__).parent / "scripts"))
    from slack_client import SlackClient
    return SlackClient()
