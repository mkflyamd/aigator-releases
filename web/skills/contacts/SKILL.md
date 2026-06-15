---
name: contacts
description: "Microsoft 365 Contacts — search, create, delete contacts."
metadata:
  author: Mayuresh Kulkarni
  version: "1.0"
  format: agentskills-1.0
---

# Contacts Workflow

- "Find contact / look up contact" → call search_contacts.
- "Delete contact" → call search_contacts first to get the contact ID, confirm with user, then call delete_contact.
- "Add contact" → confirm name, email, phone with user before calling create_contact.
