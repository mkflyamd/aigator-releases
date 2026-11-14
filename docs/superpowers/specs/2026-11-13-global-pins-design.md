# Global Pins — Design

## Goal

Let a user mark a pinned item as **global** from the pin orb popover. A global pin shows in every tab. Turning global off demotes the pin to a normal pin on the tab where the user toggled it.

## Decisions

- Un-globaling demotes to a tab pin on the calling tab (it does not delete the item).
- Clicking × on a global pin deletes it from all tabs, after a confirm.
- Global pins live in one shared bucket, not as copies in each tab.

## Backend — `web/skills/context/state.py`

- `GLOBAL_CONTEXT_ID = "__global__"`: a reserved bucket in `pinned_contexts.json`. Tab ids are random, and it is distinct from `"default"`.
- `get_pins(context_id, include_global=True)` returns the tab's pins plus global pins. Global entries are returned as copies tagged `scope: "global"`; the tag is never persisted. An item present in both places appears once, as global.
- `set_pin_scope(source, item_id, scope, context_id)` moves the entry with its meta intact:
  - `scope="global"`: tab bucket -> global bucket.
  - `scope="tab"`: global bucket -> the calling tab's bucket.
  - Returns `{"moved": bool, "scope": scope, ...}`; `moved` is false when the entry is not found.
- `remove_pin(source, item_id, context_id, scope="tab")`: `scope="global"` removes from the global bucket.
- `/api/context/pins/clone` uses `get_pins(..., include_global=False)` so cloning a tab does not copy global pins.
- Closing a tab clears only that tab's bucket; global pins are untouched.

## Routes — `web/routes/onenote.py`

- `POST /api/context/pin/scope` with body `{source, id, scope, context_id}`, `dependencies=[Depends(verify_csrf)]`.
- `DELETE /api/context/pin/{source}/{item_id:path}` accepts `?scope=global`.

## Frontend — `web/static/app.js` (`_showPinPopover`)

- Each pin card gets a globe toggle between the insert (✦) and remove (×) buttons. It is filled when the pin is global; the title reads "Make global" or "Make tab-only".
- When at least one global pin exists, the list shows a "Global" group above a "This tab" group. With none, the list looks as it does today.
- × on a global card asks "Remove from all tabs?" before deleting, and sends `scope=global`.
- List rendering moves into a function so the popover re-renders after a toggle without closing. A toggle updates the cached pin list locally (the badge count is unchanged), so no refetch or flicker.
- Badge count, the `Shift+{` dropdown, the agent prompt (`routes/chat.py`), the scheduler, and the tab/OneDrive tools read through `get_pins` and need no changes.

## Tests

- State: merge and dedupe; promote and demote with meta preserved; demote lands on the calling tab; clone excludes global; delete with `scope=global`; clearing a tab leaves global pins.
- Routes: `POST /api/context/pin/scope` round-trip; `tests/test_csrf_route_inventory.py` passes with the new route (no baseline additions).
- JS popover grouping test if the existing JS test setup makes it cheap.

## Out of scope

Pin-time "pin globally" shortcuts in Slack/Teams, a cap on global pin count, tinting of global cards.
