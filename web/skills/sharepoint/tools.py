"""SharePoint skill -- 4 tools."""
from pathlib import Path

SHAREPOINT_SKILLS_DIR = Path(__file__).parent.parent / "m365-sharepoint" / "scripts"

SKILL_ID = "sharepoint"

TOOL_DEFS = [
    {
        "name": "list_sharepoint_sites",
        "description": "List SharePoint sites the user follows. Use when user asks about SharePoint sites.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Max results. Default 20.", "default": 20},
            },
            "required": [],
        },
    },
    {
        "name": "search_sharepoint_sites",
        "description": "Search for SharePoint sites by name. Use when user wants to find a specific site.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Site name search query"},
                "count": {"type": "integer", "description": "Max results. Default 10.", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_sharepoint_drives",
        "description": "List document libraries (drives) in a SharePoint site. Call after list_sharepoint_sites to get drive IDs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "Site ID from list_sharepoint_sites or search_sharepoint_sites"},
            },
            "required": ["site_id"],
        },
    },
    {
        "name": "list_sharepoint_files",
        "description": "Browse files in a SharePoint document library. Call after list_sharepoint_drives to get drive_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "site_id": {"type": "string", "description": "Site ID"},
                "drive_id": {"type": "string", "description": "Drive ID from list_sharepoint_drives"},
                "path": {"type": "string", "description": "Subfolder path (default: root)", "default": ""},
                "count": {"type": "integer", "description": "Max items. Default 50.", "default": 50},
            },
            "required": ["site_id", "drive_id"],
        },
    },
]

TOOL_STATUS = {
    "list_sharepoint_sites": "\U0001f310 Listing SharePoint sites...",
    "search_sharepoint_sites": "\U0001f50d Searching SharePoint sites...",
    "list_sharepoint_drives": "\U0001f4c1 Listing document libraries...",
    "list_sharepoint_files": "\U0001f4c1 Browsing SharePoint files...",
}


def _tool_list_sharepoint_sites(count: int = 20) -> dict:
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(SHAREPOINT_SKILLS_DIR)
    data = gc.get("/me/followedSites", params={"$top": str(count)})
    return {"sites": [{"name": s.get("displayName", ""), "url": s.get("webUrl", ""),
                       "description": s.get("description", ""), "id": s.get("id", "")}
                      for s in data.get("value", [])]}


def _tool_search_sharepoint_sites(query: str, count: int = 10) -> dict:
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(SHAREPOINT_SKILLS_DIR)
    data = gc.get("/sites", params={"search": query, "$top": str(count)})
    return {"query": query, "sites": [{"name": s.get("displayName", ""), "url": s.get("webUrl", ""),
                                        "description": s.get("description", ""), "id": s.get("id", "")}
                                       for s in data.get("value", [])]}


def _tool_list_sharepoint_drives(site_id: str) -> dict:
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(SHAREPOINT_SKILLS_DIR)
    data = gc.get(f"/sites/{site_id}/drives")
    return {"drives": [{"name": d.get("name", ""), "description": d.get("description", ""),
                         "url": d.get("webUrl", ""), "id": d.get("id", "")}
                        for d in data.get("value", [])]}


def _tool_list_sharepoint_files(site_id: str, drive_id: str, path: str = "", count: int = 50) -> dict:
    from .._m365.helpers import get_skill_client
    gc = get_skill_client(SHAREPOINT_SKILLS_DIR)
    api_path = (f"/sites/{site_id}/drives/{drive_id}/root:/{path}:/children" if path
                else f"/sites/{site_id}/drives/{drive_id}/root/children")
    data = gc.get(api_path, params={"$top": str(count), "$orderby": "name",
                                     "$select": "name,size,lastModifiedDateTime,folder,file,webUrl,id"})
    items = []
    for item in data.get("value", []):
        is_folder = "folder" in item
        items.append({"name": item.get("name", ""), "type": "folder" if is_folder else "file",
                      "size": item.get("size", 0), "modified": item.get("lastModifiedDateTime", "")[:16],
                      "url": item.get("webUrl", ""), "id": item.get("id", "")})
    return {"path": path or "/", "total": len(items), "items": items}


TOOL_HANDLERS = {
    "list_sharepoint_sites": _tool_list_sharepoint_sites,
    "search_sharepoint_sites": _tool_search_sharepoint_sites,
    "list_sharepoint_drives": _tool_list_sharepoint_drives,
    "list_sharepoint_files": _tool_list_sharepoint_files,
}
