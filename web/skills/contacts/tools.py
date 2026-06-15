"""Contacts skill -- 3 tools."""
from pathlib import Path

CONTACTS_SKILLS_DIR = Path(__file__).parent.parent / "m365-contacts" / "scripts"

SKILL_ID = "contacts"

TOOL_DEFS = [
    {
        "name": "search_contacts",
        "description": "Search the user's personal Outlook address book (contacts). Use when the user asks about someone who may be in their personal contacts rather than the organization directory, e.g. external partners, personal contacts. For coworkers, prefer search_people instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name to search in personal contacts"},
                "count": {"type": "integer", "description": "Max results. Default 10.", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "create_contact",
        "description": "Create a new personal contact in Outlook. Use when user asks to save or add a new contact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Full display name"},
                "email": {"type": "string", "description": "Email address"},
                "phone": {"type": "string", "description": "Business phone"},
                "company": {"type": "string", "description": "Company name"},
                "title": {"type": "string", "description": "Job title"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_contact",
        "description": "Delete a personal contact by ID. Call search_contacts first to get the ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "description": "Contact ID from search_contacts"},
            },
            "required": ["contact_id"],
        },
    },
]

TOOL_STATUS = {
    "search_contacts": "\U0001f4c7 Searching contacts...",
    "create_contact": "\U0001f4c7 Creating contact...",
    "delete_contact": "\U0001f4c7 Deleting contact...",
}


def _tool_search_contacts(query: str, count: int = 10) -> dict:
    from .._m365.helpers import get_graph_client
    gc = get_graph_client()
    params = {"$top": str(count), "$orderby": "displayName",
              "$select": "id,displayName,emailAddresses,businessPhones,mobilePhone,companyName,jobTitle",
              "$filter": f"startswith(displayName,'{query}') or startswith(givenName,'{query}') or startswith(surname,'{query}')"}
    data = gc.get("/me/contacts", params=params)
    contacts = [{"name": c.get("displayName", ""), "email": (c.get("emailAddresses") or [{}])[0].get("address", ""),
                 "phone": (c.get("businessPhones") or [""])[0], "mobile": c.get("mobilePhone", ""),
                 "company": c.get("companyName", ""), "title": c.get("jobTitle", "")}
                for c in data.get("value", [])]
    return {"total": len(contacts), "contacts": contacts}


def _tool_create_contact(name: str, email: str = "", phone: str = "", company: str = "", title: str = "") -> dict:
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(CONTACTS_SKILLS_DIR)
    parts = name.rsplit(" ", 1)
    contact = {"displayName": name, "givenName": parts[0], "surname": parts[1] if len(parts) > 1 else ""}
    if email: contact["emailAddresses"] = [{"address": email, "name": name}]
    if phone: contact["businessPhones"] = [phone]
    if company: contact["companyName"] = company
    if title: contact["jobTitle"] = title
    result = gc.post("/me/contacts", contact)
    return {"created": True, "name": result.get("displayName", name), "id": result.get("id", "")}


def _tool_delete_contact(contact_id: str) -> dict:
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(CONTACTS_SKILLS_DIR)
    gc.delete(f"/me/contacts/{contact_id}")
    return {"deleted": True, "contact_id": contact_id}


TOOL_HANDLERS = {
    "search_contacts": _tool_search_contacts,
    "create_contact": _tool_create_contact,
    "delete_contact": _tool_delete_contact,
}
