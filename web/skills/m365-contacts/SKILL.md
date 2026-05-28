---
name: m365-contacts
description: "List, search, create, and delete personal Outlook contacts via the Microsoft Graph API."
metadata:
  author: AI Gator
  version: "1.0"
  format: agentskills-1.0
---

# M365 Contacts

Manages personal contacts in your Outlook / Microsoft 365 account using the Microsoft Graph API. Supports listing, searching, creating, and deleting contacts.

## When to use

Use this skill when the user wants to look up, add, or remove a contact from their personal Outlook contacts.

## Tools available

- `list_contacts` — List all personal contacts, optionally filtered by name
- `get_contact` — Get details for a specific contact by ID
- `create_contact` — Create a new contact with name, email, phone, company, and job title
- `delete_contact` — Delete a contact by ID

## Rules

- Requires Microsoft 365 authentication — prompt the user to sign in via Settings if not authenticated.
- Always confirm contact details with the user before calling `create_contact`.
- Do not delete contacts without explicit user confirmation.
