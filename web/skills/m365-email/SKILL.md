---
name: m365-email
description: "Shared Microsoft Graph API authentication client used by all m365-* skills."
metadata:
  author: AI Gator
  version: "1.0"
  format: agentskills-1.0
---

# M365 Auth (Graph Client)

Provides the shared Microsoft Graph API client (`GraphClient`) and OAuth2 device-code authentication flow used by all other m365-* skills (calendar, contacts, onedrive, onenote, people, sharepoint, teams).

## When to use

This is an internal library skill, not invoked directly. It is loaded automatically when any other m365-* skill needs to authenticate against the Microsoft Graph API.

## Tools available

- `start_auth` — Begin the device-code sign-in flow; returns the user code and verification URL
- `complete_auth` — Poll for sign-in completion and save the access and refresh tokens
- `is_authenticated` — Check whether a valid token is cached

## Rules

- Tokens are stored at `~/.config/microsoft-graph/token.json` with mode 0o600.
- Never log or expose raw access tokens or refresh tokens in output.
- If authentication fails with AADSTS65002, advise the user to re-authenticate — do not attempt to broaden requested scopes.
