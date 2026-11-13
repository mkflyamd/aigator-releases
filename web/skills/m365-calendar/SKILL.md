---
name: m365-calendar
description: 'View, create, and find meeting times on your Microsoft 365 calendar via the Graph API.'
metadata:
  author: AI Gator
  version: '1.0'
  format: agentskills-1.0
---

# M365 Calendar

Reads and writes your Microsoft 365 / Outlook calendar using the Microsoft Graph API. Supports listing events for a date range, finding available meeting slots, and deleting events. Creating meetings and out-of-office events is done by the built-in calendar tools, which draft a meeting for the user to approve.

## When to use

Use this skill when the user asks about their schedule, wants to check availability, find a meeting time, or cancel a meeting.

## Tools available

- `list_events` — List calendar events for today, a specific date, or a date range
- `find_time` — Find available meeting time slots across multiple attendees
- `delete_event` — Delete a calendar event by event ID
- `free_busy` — Check free/busy status for a list of users

## Rules

- Requires Microsoft 365 authentication — prompt the user to sign in via Settings → Apps → Microsoft 365 if not authenticated.
- Do not delete events without explicit user confirmation.
