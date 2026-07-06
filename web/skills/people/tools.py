"""People skill -- 2 tools (always-on)."""

SKILL_ID = "people"
ALWAYS_ON = True  # always available regardless of active skill

TOOL_DEFS = [
    {
        "name": "search_people",
        "description": "Search coworkers by name or email using the Microsoft Graph People API. ALWAYS call this first when the user mentions a person's name (e.g. 'send email to Tanmay', 'message Sarah', 'find John') to resolve their email address before calling send_email or send_teams_message. Returns name, email, job title, department.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name or partial name to search (e.g. 'Tanmay', 'Tanmay Shah', 'tanmay.shah@example.com')"},
                "count": {"type": "integer", "description": "Max results to return. Default 5.", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_person_profile",
        "description": "Get the full Microsoft 365 profile of a coworker by their email address or user ID. Returns name, title, department, office, phone, manager chain. Use after search_people to get more detail, or when user asks 'who is X', 'what's X's title', 'who does X report to'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "User's email / UPN (e.g. tanmay.shah@example.com). Use this or user_id."},
                "user_id": {"type": "string", "description": "Graph user ID. Use this if you have it from a prior search_people call."},
                "include_org_chain": {"type": "boolean", "description": "Also fetch the manager chain (org hierarchy). Default false.", "default": False},
            },
            "required": [],
        },
    },
]

TOOL_STATUS = {
    "search_people": "\U0001f464 Looking up person...",
    "get_person_profile": "\U0001f464 Fetching profile...",
}


def _tool_search_people(query: str, count: int = 5, org_only: bool = False) -> dict:
    """Search people, merging frequent contacts (/me/people) with the org directory (/users).

    org_only=True keeps only organization users — external Gmail/personal contacts (which have
    no Teams presence) are dropped from the /me/people results. The two Graph queries run
    concurrently so the directory search's slower eventual-consistency path doesn't add latency
    on top of the fast relationship-ranked path.
    """
    import sys
    from concurrent.futures import ThreadPoolExecutor
    from .._m365.helpers import get_graph_client
    try:
        gc = get_graph_client()

        def _fetch_people() -> list[dict]:
            """/me/people — relationship-ranked frequent contacts (fast)."""
            out = []
            try:
                data = gc.get("/me/people", params={"$search": f'"{query}"', "$top": str(count)})
                for p in data.get("value", []):
                    # org_only: drop anything that isn't an organization user (external
                    # contacts, groups, rooms). personType.subclass is the reliable signal.
                    if org_only:
                        subclass = (p.get("personType") or {}).get("subclass", "")
                        if subclass != "OrganizationUser":
                            continue
                    email = (p.get("scoredEmailAddresses") or [{}])[0].get("address", "")
                    if email:
                        out.append({"name": p.get("displayName", ""), "email": email,
                                    "job_title": p.get("jobTitle", ""), "department": p.get("department", ""),
                                    "office": p.get("officeLocation", ""), "id": p.get("id", "")})
            except Exception:
                pass
            return out

        def _fetch_users() -> list[dict]:
            """/users — full directory search, fills gaps /me/people misses (slower)."""
            out = []
            try:
                select = "displayName,mail,userPrincipalName,jobTitle,department,officeLocation,id"
                dir_data = gc.get("/users", params={
                    "$search": f'"displayName:{query}"',
                    "$select": select,
                    "$top": str(count),
                }, extra_headers={"ConsistencyLevel": "eventual"})
                for u in dir_data.get("value", []):
                    email = u.get("mail") or u.get("userPrincipalName", "")
                    if email:
                        out.append({"name": u.get("displayName", ""), "email": email,
                                    "job_title": u.get("jobTitle", ""), "department": u.get("department", ""),
                                    "office": u.get("officeLocation", ""), "id": u.get("id", "")})
            except Exception as dir_err:
                print(f"[people/users] directory search failed: {dir_err}", file=sys.stderr, flush=True)
            return out

        # Run both concurrently — the /users eventual-consistency path is the slow one, so
        # overlapping it with /me/people means total latency ≈ max(one call), not the sum.
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_people = ex.submit(_fetch_people)
            f_users = ex.submit(_fetch_users)
            frequent = f_people.result()
            directory = f_users.result()

        # Merge: frequent contacts first (relationship-ranked), directory fills the rest.
        people = []
        seen_emails = set()
        for src in (frequent, directory):
            for p in src:
                email = p["email"].lower()
                if email not in seen_emails:
                    seen_emails.add(email)
                    people.append(p)

        return {"total": len(people), "people": people[:count]}
    except Exception as e:
        return {"error": str(e)}


def _tool_get_person_profile(email: str = "", user_id: str = "", include_org_chain: bool = False) -> dict:
    from .._m365.helpers import get_graph_client
    try:
        gc = get_graph_client()
        if email: path = f"/users/{email}"
        elif user_id: path = f"/users/{user_id}"
        else: path = "/me"
        user = gc.get(path)
        profile = {"name": user.get("displayName", ""), "email": user.get("mail", "") or user.get("userPrincipalName", ""),
                   "job_title": user.get("jobTitle", ""), "department": user.get("department", ""),
                   "office": user.get("officeLocation", ""), "phone": (user.get("businessPhones") or [""])[0],
                   "mobile": user.get("mobilePhone", ""), "city": user.get("city", ""), "id": user.get("id", "")}
        if include_org_chain:
            chain = []
            current = path
            for _ in range(5):
                try:
                    mgr = gc.get(f"{current}/manager")
                    chain.append({"name": mgr.get("displayName", ""), "email": mgr.get("mail", "") or mgr.get("userPrincipalName", ""),
                                  "job_title": mgr.get("jobTitle", "")})
                    current = f"/users/{mgr.get('id', '')}"
                    if not mgr.get("id"): break
                except Exception: break
            profile["org_chain"] = chain
        return profile
    except Exception as e:
        return {"error": str(e)}


TOOL_HANDLERS = {
    "search_people": _tool_search_people,
    "get_person_profile": _tool_get_person_profile,
}
