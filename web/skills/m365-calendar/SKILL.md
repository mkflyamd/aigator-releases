---
name: m365-calendar
description: "View, create, and find meeting times on your Microsoft 365 calendar via the Graph API."
metadata:
  author: AI Gator
  version: "1.0"
  format: agentskills-1.0
---

# M365 Calendar

Reads and writes your Microsoft 365 / Outlook calendar using the Microsoft Graph API. Supports listing events for a date range, creating meetings with attendees and Teams links, finding available meeting slots, and deleting events.

## When to use

Use this skill when the user asks about their schedule, wants to check availability, find a meeting time, create a calendar event, or cancel a meeting.

## Tools available

- `list_events` — List calendar events for today, a specific date, or a date range
- `create_event` — Create a new calendar event, optionally with attendees and a Teams meeting link
- `find_time` — Find available meeting time slots across multiple attendees
- `delete_event` — Delete a calendar event by event ID
- `free_busy` — Check free/busy status for a list of users
- `create_ooo` — Create an out-of-office (all-day) event block

## Rules

- Requires Microsoft 365 authentication — prompt the user to sign in via Settings if not authenticated.
- When creating events with attendees, always confirm the details (subject, time, attendees) with the user before calling `create_event`.
- Do not delete events without explicit user confirmation.
