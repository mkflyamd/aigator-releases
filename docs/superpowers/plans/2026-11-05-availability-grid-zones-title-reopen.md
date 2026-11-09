# Availability Grid Time Zones, Title and Message, and Reopen in Outlook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The availability grid shows the picked slot in each attendee's time zone, carries a Title and Message into Outlook, and the Open in Outlook buttons (grid and calendar draft card) work again after the Outlook window is closed.

**Architecture:** The server reads each attendee's zone once from Graph working hours (`timezones.attendee_zones`) and puts it on `grid.people[i].timezone`; a new no-Graph route converts a picked slot into per-zone lines. The grid card gets Title and Message fields built with `_jiraEditRow`. The Electron shell tells the renderer when the compose popout closes, and a shared `_watchOutlookComposeClosed` helper lets both cards re-enable their button and reopen the stored URL with no server call.

**Tech Stack:** Python 3 / FastAPI / pytest, vanilla JS (`web/static/app.js`, tested with `node` + `vm`), Electron (`shell/main.js`, `shell/preload.js`).

Spec: `docs/superpowers/specs/2026-11-05-availability-grid-zones-title-reopen-design.md`

## Global Constraints

- No `Co-Authored-By` lines in commit messages (CLAUDE.md overrides any default attribution).
- Every new POST route uses `dependencies=[Depends(verify_csrf)]`; do not touch `tests/csrf_route_baseline.txt`. `tests/test_csrf_route_inventory.py` must pass.
- `aigator-fake-api-key` is the only fake credential in tests and docs. Use `example.com` style emails as the existing tests do.
- The product is "AI Gator", never "POC".
- Human-in-the-loop: nothing is sent automatically. Open in Outlook only opens an unsent draft or compose window; Send invite stays blocked after any hand-off.
- Time zone labels come from `timezones.fmt_range`, so they match the draft card (including `(+1 day)`).
- The grid zone's own line is omitted from the zone lines; people with an unknown zone are left out.
- The one-off compose-link tooltip reads exactly: "Opens a new invite. If you already sent it in Outlook, don't send it again."
- Without the Electron shell there is no close signal, so the button is re-enabled right after the click.
- Do the least that meets the spec: no extra settings, no new options, no caveat notes in docs.

## Working notes for every task

- Run Python tests from the repo root: `python -m pytest <path> -q`. Run JS tests directly: `node tests/<file>.test.js`. CI runs `npm --prefix shell test`.
- The working tree has CRLF line endings (the index is LF; git normalizes on commit). After an Edit that spans several lines, confirm it applied; if a multi-line `old_string` fails to match, anchor on a single line instead.
- Format before committing JS: `npx prettier --write web/static/app.js shell/main.js shell/preload.js tests/availability_grid_card.test.js tests/outlook_standalone_nav.test.js tests/calendar_draft_card.test.js` (only the files you changed). Python style: match the surrounding code (4-space indent, double quotes).
- `app.js` has a startup `const` ordering hazard: inside `_showAvailabilityGrid`, declare every variable that `syncOutlookLink()` or the repeat-panel callback touches ABOVE the `const panel = _availabilityGridRepeatPanel(...)` line, or the card dies with a TDZ error.

## File Structure

| File | Change |
|---|---|
| `web/skills/calendar/tools.py` | `show_availability_grid` schema and function gain `subject`, `body`; grid people get `timezone`; `_tool_load_availability_days` gains `with_zones` |
| `web/routes/calendar.py` | `AvailabilityDaysRequest.zones`; `GridSeriesRequest.subject/body`; new `POST /api/calendar/slot-zones` |
| `shell/main.js` | `outlook-pane:open-compose-window` sends `outlook-pane:compose-closed` |
| `shell/preload.js` | `onOutlookComposeClosed(callback)` returning an unsubscribe function |
| `web/static/app.js` | pure helpers, grid Title/Message/zone lines/reopen, draft card reopen |
| `web/static/style.css` | `.ag-details`, `.ag-chosen-box`, `.ag-zones` |
| `web/tests/test_availability_grid.py` | zone and subject/body tests |
| `tests/test_grid_slot_zones.py` (new) | slot-zones route and availability-days `zones` flag |
| `tests/test_grid_draft_series.py` | subject/body reach the Graph event |
| `tests/outlook_standalone_nav.test.js` | close IPC and preload asserts |
| `tests/availability_grid_card.test.js` | helper tests and source asserts for the grid |
| `tests/calendar_draft_card.test.js` | reopen asserts; open-handler assert moves to the helper |

---

### Task 1: Server puts time zones, Title and Message on the grid payload

**Files:**
- Modify: `web/skills/calendar/tools.py` (schema ~273-302, `_tool_load_availability_days` ~789-818, `_tool_show_availability_grid` ~824-871)
- Test: `web/tests/test_availability_grid.py`

**Interfaces:**
- Consumes: `timezones.attendee_zones(gc, emails, day, win_tz) -> {email_lower: {"timezone": str, "working_hours": str}}` (already exists in `web/skills/calendar/timezones.py`).
- Produces: `grid.people[i].timezone` (Windows zone name, present only when known; never on "You"); `grid.subject`, `grid.body` (strings, `""` when not given); `_tool_load_availability_days(emails, after_date="", duration_minutes=30, count=10, dates=None, with_zones=False)` returns `{"days": [...], "zones": {email: zone_name}}` when `with_zones` is true, else only `{"days": [...]}`.

- [ ] **Step 1: Write the failing tests**

In `web/tests/test_availability_grid.py`, change `_run` to accept an optional fake client, and add a zone-aware fake next to `_Gc`:

```python
class _ZoneGc(_Gc):
    """Adds working hours to the one-hour getSchedule that reads each person's time zone."""

    def __init__(self, views, zones):
        super().__init__(views)
        self.zones = zones

    def post(self, path, body):
        out = super().post(path, body)
        if body.get("availabilityViewInterval") == 60:
            for item in out["value"]:
                zone = self.zones.get(item["scheduleId"])
                if zone:
                    item["workingHours"] = {
                        "timeZone": {"name": zone},
                        "startTime": "08:00:00.0000000",
                        "endTime": "17:00:00.0000000",
                    }
        return out


def _run(views, gc=None, **kw):
    import skills._m365.helpers  # noqa: F401
    import skills.calendar.helpers  # noqa: F401

    gc = gc or _Gc(views)
    with (
        patch("skills._m365.helpers.get_cal_client", return_value=gc),
        patch("skills._m365.helpers.get_cached_me", return_value={"mail": "me@example.com"}),
        patch("skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"),
    ):
        return _tool_show_availability_grid(**kw), gc
```

Append these tests at the end of the file:

```python
def test_people_carry_their_time_zone_from_working_hours():
    views = {e: "0" * 48 for e in ("me@example.com", "tej@example.com", "faisal@example.com", "ghost@example.com")}
    gc = _ZoneGc(views, {"tej@example.com": "Central Standard Time", "faisal@example.com": "GMT Standard Time"})
    out, _ = _run(
        views,
        gc=gc,
        attendees=["tej@example.com", "faisal@example.com", "ghost@example.com"],
        dates=["2030-01-07"],
    )
    zones = {p["email"]: p.get("timezone") for p in out["_availability_grid"]["people"]}
    assert zones == {
        "me@example.com": None,
        "tej@example.com": "Central Standard Time",
        "faisal@example.com": "GMT Standard Time",
        "ghost@example.com": None,
    }


def test_the_grid_carries_the_title_and_message_it_was_given():
    views = {"me@example.com": "0" * 48}
    base = {"attendees": ["a@example.com"], "dates": ["2030-01-07"]}
    grid = _run(views, subject="Design sync", body="Agenda: roadmap", **base)[0]["_availability_grid"]
    assert grid["subject"] == "Design sync" and grid["body"] == "Agenda: roadmap"
    grid = _run(views, **base)[0]["_availability_grid"]
    assert grid["subject"] == "" and grid["body"] == ""


def test_adding_a_person_can_return_their_zone():
    import skills._m365.helpers  # noqa: F401
    import skills.calendar.helpers  # noqa: F401
    from skills.calendar.tools import _tool_load_availability_days

    dates = [(date.today() + timedelta(days=30)).isoformat()]
    gc = _ZoneGc({"new@example.com": "0" * 48}, {"new@example.com": "Arabian Standard Time"})
    with (
        patch("skills._m365.helpers.get_cal_client", return_value=gc),
        patch("skills.calendar.helpers.get_user_win_tz", return_value="Pacific Standard Time"),
    ):
        with_zones = _tool_load_availability_days(["new@example.com"], dates=dates, with_zones=True)
        without = _tool_load_availability_days(["new@example.com"], dates=dates)
    assert with_zones["zones"] == {"new@example.com": "Arabian Standard Time"}
    assert "zones" not in without
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest web/tests/test_availability_grid.py -q`
Expected: the three new tests FAIL (`KeyError: 'subject'`, `unexpected keyword argument 'subject'`, `unexpected keyword argument 'with_zones'`); the existing tests still pass.

- [ ] **Step 3: Implement**

In `web/skills/calendar/tools.py`, add two optional properties to the `show_availability_grid` schema, after the `recurrence` property (before the closing `},` of `properties` at ~line 299):

```python
                "subject": {
                    "type": "string",
                    "description": "Meeting title, when the user gave one. Pre-fills the card's Title box.",
                },
                "body": {
                    "type": "string",
                    "description": "Meeting message or agenda, when the user gave one. Pre-fills the card's Message box.",
                },
```

Change `_tool_load_availability_days`:

```python
def _tool_load_availability_days(
    emails: list,
    after_date: str = "",
    duration_minutes: int = 30,
    count: int = 10,
    dates: list | None = None,
    with_zones: bool = False,
) -> dict:
```

and replace its last line (`return {"days": ...}`) with:

```python
    gc, win_tz = get_cal_client(), get_user_win_tz()
    out: dict = {"days": _grid_day_payloads(gc, wanted, day_list, win_tz, need, now)}
    if with_zones:
        from . import timezones

        found = timezones.attendee_zones(gc, wanted, day_list[0].isoformat(), win_tz)
        out["zones"] = {email: info["timezone"] for email, info in found.items()}
    return out
```

Change `_tool_show_availability_grid`'s signature to:

```python
def _tool_show_availability_grid(
    attendees: list,
    dates: list | None = None,
    duration_minutes: int = 30,
    recurrence: str = "none",
    subject: str = "",
    body: str = "",
) -> dict:
```

After `days = _grid_day_payloads(...)` (the zone lookup must come after it so the first Graph call is still the free/busy read), add:

```python
    from . import timezones

    found = timezones.attendee_zones(gc, emails[1:], days[0]["date"] if days else "", win_tz)
    for person in people:
        if person["email"] in found:
            person["timezone"] = found[person["email"]]["timezone"]
```

and add to the `grid = {...}` dict, after `"repeat": repeat,`:

```python
        "subject": str(subject or ""),
        "body": str(body or ""),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest web/tests/test_availability_grid.py -q`
Expected: all pass (the existing tests that count `gc.calls` use `_tool_load_availability_days` without `with_zones`, so they are unaffected).

- [ ] **Step 5: Check nothing else depends on the grid call count**

Run: `python -m pytest web/tests tests -q -k "availability or calendar or grid"`
Expected: PASS. If a test fails because the grid now makes one extra `getSchedule` call, update that test's expected count by one.

- [ ] **Step 6: Commit**

```bash
git add web/skills/calendar/tools.py web/tests/test_availability_grid.py
git commit -m "feat: availability grid carries attendee time zones and an optional title and message"
```

---

### Task 2: Server routes: slot-zones, availability-days zones flag, grid-draft-series subject and body

**Files:**
- Modify: `web/routes/calendar.py` (`AvailabilityDaysRequest` ~23, `GridSeriesRequest` ~139, `tp_calendar_grid_draft_series` ~205-236, `tp_calendar_availability_days` ~239-256)
- Create: `tests/test_grid_slot_zones.py`
- Test: `tests/test_grid_draft_series.py`

**Interfaces:**
- Consumes: `timezones.fmt_range(start, end, from_tz, to_tz) -> str | None`; `_tool_load_availability_days(..., with_zones)` from Task 1.
- Produces:
  - `POST /api/calendar/slot-zones`, body `{start, end, timezone, zones: {email: zone_name}}`, returns a JSON list `[{"label": "11:00 AM – 11:30 AM CST", "people": [email, ...]}]` in first-appearance order. The grid's own line and unknown zones are omitted. `people` holds the request's email keys; the client maps them to display names.
  - `POST /api/calendar/availability-days` accepts `zones: bool = False` and forwards it as `with_zones`.
  - `POST /api/calendar/grid-draft-series` accepts `subject: str = ""`, `body: str = ""`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_grid_slot_zones.py`:

```python
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from security import get_csrf_token


def _post(path, body):
    return TestClient(app).post(path, headers={"X-CSRF-Token": get_csrf_token("testserver")}, json=body)


SLOT = {"start": "2026-11-10T09:00:00", "end": "2026-11-10T09:30:00", "timezone": "Pacific Standard Time"}


def test_slot_zones_groups_people_who_share_a_result():
    res = _post(
        "/api/calendar/slot-zones",
        {
            **SLOT,
            "zones": {
                "aswin@example.com": "Central Standard Time",
                "faisal@example.com": "GMT Standard Time",
                "tej@example.com": "Central Standard Time",
            },
        },
    )
    assert res.status_code == 200
    assert res.json() == [
        {"label": "11:00 AM – 11:30 AM CST", "people": ["aswin@example.com", "tej@example.com"]},
        {"label": "5:00 PM – 5:30 PM GMT", "people": ["faisal@example.com"]},
    ]


def test_slot_zones_leaves_out_the_grid_zone_and_unknown_zones():
    res = _post(
        "/api/calendar/slot-zones",
        {
            **SLOT,
            "zones": {
                "diwakar@example.com": "Pacific Standard Time",
                "nobody@example.com": "No Such Zone",
                "tej@example.com": "Central Standard Time",
            },
        },
    )
    assert res.json() == [{"label": "11:00 AM – 11:30 AM CST", "people": ["tej@example.com"]}]


def test_slot_zones_makes_no_graph_call():
    with patch("skills._m365.helpers.get_cal_client", side_effect=AssertionError("no Graph call")):
        res = _post("/api/calendar/slot-zones", {**SLOT, "zones": {"tej@example.com": "Central Standard Time"}})
    assert res.status_code == 200


def test_slot_zones_rejects_a_flood_of_people():
    zones = {f"p{n}@example.com": "Central Standard Time" for n in range(41)}
    assert _post("/api/calendar/slot-zones", {**SLOT, "zones": zones}).status_code == 400


def test_availability_days_passes_the_zones_flag_on():
    seen = {}

    def fake(emails, after_date, duration, count, dates, with_zones):
        seen["with_zones"] = with_zones
        return {"days": [], "zones": {}}

    with patch("skills.calendar.tools._tool_load_availability_days", side_effect=fake):
        res = _post(
            "/api/calendar/availability-days",
            {"emails": ["a@example.com"], "dates": ["2030-01-07"], "zones": True},
        )
    assert res.status_code == 200 and seen["with_zones"] is True
```

Append to `tests/test_grid_draft_series.py`:

```python
def test_route_carries_the_title_and_message_into_the_draft():
    gc = MagicMock()
    gc.post.return_value = {"id": "evt1", "webLink": "https://outlook.office365.com/owa/?itemid=evt1"}
    with patch("skills._m365.helpers.get_cal_client", return_value=gc):
        res = _post({**BODY, "subject": "Design sync", "body": "Agenda: roadmap"})
    assert res.status_code == 200
    event = gc.post.call_args.args[1]
    assert event["subject"] == "Design sync"
    assert event["body"] == {"contentType": "text", "content": "Agenda: roadmap"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_grid_slot_zones.py tests/test_grid_draft_series.py -q`
Expected: the slot-zones tests FAIL with 404/405 (route missing); the availability-days flag test FAILS (`zones` ignored, fake called with 5 args → TypeError → 500); the subject/body test FAILS (`event["subject"] == ""`).

- [ ] **Step 3: Implement**

In `web/routes/calendar.py`:

`AvailabilityDaysRequest` gains a field after `duration_minutes`:

```python
    zones: bool = False
```

`GridSeriesRequest` gains two fields after `repeat`:

```python
    subject: str = ""
    body: str = ""
```

In `tp_calendar_grid_draft_series`, add to the dict passed to `_calendar_event_payload`, after `"recurrence": recurrence,`:

```python
            "subject": req.subject,
            "body": req.body,
```

In `tp_calendar_availability_days`, pass the flag as the sixth argument:

```python
        result = await asyncio.to_thread(
            _tool_load_availability_days, req.emails, req.after_date, req.duration_minutes, 10, req.dates, req.zones
        )
```

Add the new route and its request model after `tp_calendar_availability_days`:

```python
class SlotZonesRequest(BaseModel):
    start: str
    end: str
    timezone: str
    zones: dict[str, str] = {}


@router.post("/api/calendar/slot-zones", dependencies=[Depends(verify_csrf)])
async def tp_calendar_slot_zones(req: SlotZonesRequest):
    """The picked slot as clock times in each attendee's zone, grouped by identical result. No Graph call."""
    from skills.calendar import timezones

    if len(req.zones) > 40:
        raise HTTPException(status_code=400, detail="Too many people.")
    own = timezones.fmt_range(req.start, req.end, req.timezone, req.timezone)
    groups: dict[str, list[str]] = {}
    for email, zone in req.zones.items():
        label = timezones.fmt_range(req.start, req.end, req.timezone, zone)
        if label and label != own:
            groups.setdefault(label, []).append(email)
    return [{"label": label, "people": people} for label, people in groups.items()]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_grid_slot_zones.py tests/test_grid_draft_series.py tests/test_csrf_route_inventory.py -q`
Expected: all pass, including the CSRF inventory (the new route has the dependency; the baseline file is untouched).

- [ ] **Step 5: Commit**

```bash
git add web/routes/calendar.py tests/test_grid_slot_zones.py tests/test_grid_draft_series.py
git commit -m "feat: slot-zones route and title and message on grid draft series"
```

---

### Task 3: Shell tells the renderer when the compose window closes

**Files:**
- Modify: `shell/main.js` (~4628-4651), `shell/preload.js` (after line 34)
- Test: `tests/outlook_standalone_nav.test.js` (~183-190)

**Interfaces:**
- Produces: IPC event `outlook-pane:compose-closed` with the original URL string, sent to the window that called `outlook-pane:open-compose-window`. `window.gatorShell.onOutlookComposeClosed(callback)` calls `callback(url)` for each close and returns a function that unsubscribes.

- [ ] **Step 1: Write the failing test**

In `tests/outlook_standalone_nav.test.js`, after the existing `assert(/_confirmLeaveOutlookPage\(e, compose\)/...)` line and before `const preload = ...`, add the popout assert; after the existing preload `openOutlookCompose` assert, add the preload asserts:

```js
  assert(
    /compose\.on\('closed'[\s\S]*?\.send\('outlook-pane:compose-closed', String\(url\)\)/.test(
      popout[0],
    ),
    'tells the opener when the compose window closes',
  );
```

```js
  assert(
    /onOutlookComposeClosed:[\s\S]*?ipcRenderer\.on\('outlook-pane:compose-closed'[\s\S]*?ipcRenderer\.removeListener\('outlook-pane:compose-closed'/.test(
      preload,
    ),
    'preload exposes a subscription that can be removed',
  );
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/outlook_standalone_nav.test.js`
Expected: FAIL with `tells the opener when the compose window closes`.

- [ ] **Step 3: Implement**

In `shell/main.js`, change the handler signature `(_e, url)` to `(event, url)` and add the close hook just before `compose.loadURL(String(url));`:

```js
  const opener = event.sender;
  compose.on('closed', () => {
    if (!opener.isDestroyed()) opener.send('outlook-pane:compose-closed', String(url));
  });
```

In `shell/preload.js`, after the `openOutlookCompose` line add:

```js
  onOutlookComposeClosed: (callback) => {
    const listener = (_event, url) => callback(url);
    ipcRenderer.on('outlook-pane:compose-closed', listener);
    return () => ipcRenderer.removeListener('outlook-pane:compose-closed', listener);
  },
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node tests/outlook_standalone_nav.test.js`
Expected: prints `outlook_standalone_nav ok`.

- [ ] **Step 5: Commit**

```bash
npx prettier --write shell/main.js shell/preload.js tests/outlook_standalone_nav.test.js
git add shell/main.js shell/preload.js tests/outlook_standalone_nav.test.js
git commit -m "feat: shell reports when the Outlook compose window closes"
```

---

### Task 4: Pure JS helpers

**Files:**
- Modify: `web/static/app.js` (helpers near `_availabilityGridComposeUrl` ~10251 and `_availabilityGridAttendeeText` ~10283)
- Test: `tests/availability_grid_card.test.js`

**Interfaces:**
- Produces (top-level functions in `app.js`):
  - `_availabilityGridComposeUrl(grid, dayIndex, slotIndex, details)`: same as today; `details` is optional `{subject, body}`, which become `subject` and `body` query parameters when non-empty.
  - `_availabilityGridDetailsText(details) -> string`: `" Meeting title: X."` and/or `" Meeting message: Y"` (no trailing period after the message), `""` when both are empty.
  - `_availabilityGridZoneLines(zones, grid) -> string[]`: `"11:00 AM – 11:30 AM CST · Aswin, Tej"` per item of the slot-zones response; emails are shown as `person.name || person.email` using `grid.people`.
  - `_watchOutlookComposeClosed(url, onClosed)`: calls `onClosed()` once when the shell reports that `url`'s window closed, then unsubscribes; calls `onClosed()` immediately when there is no Electron shell or an older preload without `onOutlookComposeClosed`.

- [ ] **Step 1: Write the failing tests**

In `tests/availability_grid_card.test.js`, after the existing compose-URL asserts (the line asserting `to` equals `'sherry@example.com;james@example.com'`), add:

```js
const detailed = new URL(
  composeUrl(
    { ...grid, people: [{ you: true, email: 'me@example.com' }, { email: 'sherry@example.com' }] },
    1,
    19,
    { subject: 'Design sync', body: 'Agenda & notes' },
  ),
);
assert.strictEqual(detailed.searchParams.get('subject'), 'Design sync');
assert.strictEqual(detailed.searchParams.get('body'), 'Agenda & notes');
assert.strictEqual(url.searchParams.get('subject'), null, 'no details, no subject parameter');

const detailsText = load('_availabilityGridDetailsText');
assert.strictEqual(detailsText({}), '');
assert.strictEqual(detailsText({ subject: ' Sync ', body: '' }), ' Meeting title: Sync.');
assert.strictEqual(
  detailsText({ subject: 'Sync', body: 'Line one\nLine two' }),
  ' Meeting title: Sync. Meeting message: Line one\nLine two',
);

const zoneLines = load('_availabilityGridZoneLines');
assert.deepStrictEqual(
  [
    ...zoneLines(
      [
        { label: '11:00 AM – 11:30 AM CST', people: ['aswin@example.com', 'tej@example.com'] },
        { label: '5:00 PM – 5:30 PM GMT', people: ['faisal@example.com', 'x@example.com'] },
      ],
      {
        people: [
          { you: true, email: 'me@example.com' },
          { name: 'Aswin', email: 'aswin@example.com' },
          { name: 'Tej', email: 'tej@example.com' },
          { name: 'Faisal', email: 'faisal@example.com' },
        ],
      },
    ),
  ],
  ['11:00 AM – 11:30 AM CST · Aswin, Tej', '5:00 PM – 5:30 PM GMT · Faisal, x@example.com'],
);
assert.deepStrictEqual([...zoneLines(null, { people: [] })], []);

let fire = null;
const shell = {
  isShell: true,
  onOutlookComposeClosed(cb) {
    fire = cb;
    return () => {
      fire = null;
    };
  },
};
const watch = load('_watchOutlookComposeClosed', { window: { gatorShell: shell } });
let closed = 0;
watch('https://outlook.office.com/a', () => closed++);
fire('https://outlook.office.com/other');
assert.strictEqual(closed, 0, 'another window closing is ignored');
fire('https://outlook.office.com/a');
assert.strictEqual(closed, 1, 'its own window closing re-enables the button');
assert.strictEqual(fire, null, 'and unsubscribes');
const watchPlain = load('_watchOutlookComposeClosed', { window: {} });
watchPlain('https://outlook.office.com/a', () => closed++);
assert.strictEqual(closed, 2, 'without the shell the button is ready straight away');
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/availability_grid_card.test.js`
Expected: FAIL (`subject` is null; or `_availabilityGridDetailsText found in app.js`).

- [ ] **Step 3: Implement**

In `web/static/app.js`, extend `_availabilityGridComposeUrl`:

```js
function _availabilityGridComposeUrl(grid, dayIndex, slotIndex, details) {
  const times = _availabilityGridSlotTimes(grid, dayIndex, slotIndex);
  const query = {
    path: '/calendar/action/compose',
    rru: 'addevent',
    subject: (details && details.subject) || '',
    body: (details && details.body) || '',
    startdt: times.start,
    enddt: times.end,
    to: grid.people
      .filter((p) => !p.you && p.email)
      .map((p) => p.email)
      .join(';'),
  };
  ...unchanged...
```

Add after `_availabilityGridAttendeeText`:

```js
function _availabilityGridDetailsText(details) {
  const subject = String((details && details.subject) || '').trim();
  const message = String((details && details.body) || '').trim();
  return (subject ? ` Meeting title: ${subject}.` : '') + (message ? ` Meeting message: ${message}` : '');
}

function _availabilityGridZoneLines(zones, grid) {
  const names = new Map(grid.people.map((p) => [p.email, p.name || p.email]));
  return (Array.isArray(zones) ? zones : []).map(
    (z) => `${z.label} · ${(z.people || []).map((e) => names.get(e) || e).join(', ')}`,
  );
}

// Calls onClosed once the shell reports that the compose window opened for `url` was closed.
// Outside the Electron shell there is no signal, so the caller gets its button back at once.
function _watchOutlookComposeClosed(url, onClosed) {
  const shell = window.gatorShell;
  if (!shell || !shell.isShell || !shell.onOutlookComposeClosed) {
    onClosed();
    return;
  }
  const stop = shell.onOutlookComposeClosed((closedUrl) => {
    if (closedUrl !== url) return;
    stop();
    onClosed();
  });
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `node tests/availability_grid_card.test.js`
Expected: exits 0 with no assertion output.

- [ ] **Step 5: Commit**

```bash
npx prettier --write web/static/app.js tests/availability_grid_card.test.js
git add web/static/app.js tests/availability_grid_card.test.js
git commit -m "feat: grid helpers for compose details, zone lines, and the Outlook close signal"
```

---

### Task 5: Grid card UI: Title and Message, zone lines, reopen

**Files:**
- Modify: `web/static/app.js` (`_showAvailabilityGrid` ~10705-11333), `web/static/style.css` (near `.ag-chosen` ~6593)
- Test: `tests/availability_grid_card.test.js` (source asserts)

**Interfaces:**
- Consumes: Task 4 helpers; `_jiraEditRow(name, label, value, kind)` and `_jiraEditSeed`; `POST /api/calendar/slot-zones`; `POST /api/calendar/availability-days` with `zones: true`; `POST /api/calendar/grid-draft-series` with `subject`/`body`; `window.gatorShell.openOutlookCompose`.
- Produces: the grid card behaviour described in the spec sections 1-3.

- [ ] **Step 1: Write the failing source asserts**

Append to `tests/availability_grid_card.test.js`, before the final summary/`console.log` if there is one (otherwise at the end):

```js
const gridCard = source.match(/function _showAvailabilityGrid\([\s\S]*?\r?\n\}\r?\n/);
assert(gridCard, 'grid card found');
const card = gridCard[0];
assert(
  /_jiraEditRow\('subject', 'Title'[\s\S]*_jiraEditRow\('body', 'Message'/.test(card),
  'the grid has Title and Message boxes',
);
assert(
  /_availabilityGridComposeUrl\(grid, pickedAt\.di, pickedAt\.k, detailValues\(\)\)/.test(card),
  'a one-time Open in Outlook carries the title and message',
);
assert(
  /postGridJson\('\/api\/calendar\/grid-draft-series', \{[\s\S]*?\.\.\.detailValues\(\)/.test(card),
  'a server-made draft carries the title and message',
);
assert(
  /_availabilityGridDetailsText\(detailValues\(\)\)/.test(card),
  'Use this time hands the title and message to the model',
);
assert(
  /postGridJson\('\/api\/calendar\/slot-zones'/.test(card) &&
    /_availabilityGridZoneLines\(/.test(card),
  'picking a slot shows the time in each attendee zone',
);
assert(/zones: true/.test(card), 'adding a person also loads their zone');
assert(
  /_watchOutlookComposeClosed\(url,/.test(card) && /if \(openedUrl\)/.test(card),
  'Open in Outlook comes back after the window closes and reopens the stored URL',
);
assert(!/Draft opened in Outlook|Draft series opened in Outlook/.test(card), 'no stuck label');
assert(
  card.indexOf('let openedUrl') < card.indexOf('_availabilityGridRepeatPanel(() =>'),
  'state used by syncOutlookLink is declared before the repeat panel callback can run',
);
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/availability_grid_card.test.js`
Expected: FAIL with `the grid has Title and Message boxes`.

- [ ] **Step 3: Implement in `_showAvailabilityGrid`**

(a) Immediately before `const footer = document.createElement('div');` (~line 10965) add the fields and shared state:

```js
  const details = document.createElement('div');
  details.className = 'ag-details';
  details.innerHTML =
    _jiraEditRow('subject', 'Title', grid.subject || '', 'line') +
    _jiraEditRow('body', 'Message', grid.body || '', 'text');
  const detailFields = [...details.querySelectorAll('[data-jira-edit]')];
  const detailValues = () => ({
    subject: details.querySelector('[data-jira-edit="subject"]').value.trim(),
    body: details.querySelector('[data-jira-edit="body"]').value.trim(),
  });
  let openedUrl = '';
  let zoneSeq = 0;
  const SAME_INVITE_NOTE =
    "Opens a new invite. If you already sent it in Outlook, don't send it again.";
```

(b) Replace `footer.append(chosen, actions);` with:

```js
  const chosenBox = document.createElement('div');
  chosenBox.className = 'ag-chosen-box';
  const zoneBox = document.createElement('div');
  zoneBox.className = 'ag-zones';
  chosenBox.append(chosen, zoneBox);
  footer.append(chosenBox, actions);
```

(c) Add the zone loader next to `pick()` and call it at the end of `pick()` (after `syncOutlookLink();`), and clear it in `refresh()`'s "picked cleared" branch:

```js
  async function showZones(di, k) {
    const mine = ++zoneSeq;
    zoneBox.replaceChildren();
    const zones = {};
    grid.people.forEach((p) => {
      if (!p.you && p.email && p.timezone) zones[p.email] = p.timezone;
    });
    if (!Object.keys(zones).length) return;
    try {
      const slot = _availabilityGridSlotTimes(grid, di, k);
      const lines = await postGridJson('/api/calendar/slot-zones', {
        start: slot.start,
        end: slot.end,
        timezone: grid.timezone,
        zones,
      });
      if (mine !== zoneSeq) return;
      _availabilityGridZoneLines(lines, grid).forEach((text) => {
        const line = document.createElement('div');
        line.textContent = text;
        zoneBox.appendChild(line);
      });
    } catch {
      // The zone lines are a convenience; the chosen time above still shows.
    }
  }
```

In `pick()` add `showZones(di, k);` as the last statement. In `refresh()`'s else-branch (where `picked = null;`) add `zoneSeq++; zoneBox.replaceChildren();`.

(d) In `syncOutlookLink()` add at the top (after `const repeating = ...`):

```js
    openedUrl = '';
    detailFields.forEach((el) => (el.disabled = false));
```

(e) Add the open helpers right after `syncOutlookLink()` / the `repeat.addEventListener('change', ...)` block:

```js
  function showOpened(url) {
    openedUrl = url;
    detailFields.forEach((el) => (el.disabled = true));
    openOutlook.disabled = true;
    openOutlook.textContent = 'Opened in Outlook ↗';
    openOutlook.classList.add('gcc-handed-off');
    _watchOutlookComposeClosed(url, () => {
      if (openedUrl !== url) return;
      openOutlook.disabled = false;
      openOutlook.textContent = 'Open in Outlook ↗';
      openOutlook.classList.remove('gcc-handed-off');
      openOutlook.title = url.includes('/deeplink/compose')
        ? SAME_INVITE_NOTE
        : 'Opens the draft you already created in Outlook';
    });
  }

  async function launchOutlook(url) {
    openedUrl = url;
    if (typeof window.gatorShell !== 'undefined' && window.gatorShell.openOutlookCompose) {
      await window.gatorShell.openOutlookCompose(url);
    } else {
      window.open(url, '_blank', 'noopener');
    }
    showOpened(url);
  }
```

(f) Replace the whole `openOutlook.addEventListener('click', ...)` handler with:

```js
  openOutlook.addEventListener('click', async (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!pickedAt || openOutlook.disabled) return;
    if (openedUrl) {
      openOutlook.disabled = true;
      try {
        await launchOutlook(openedUrl);
      } catch (err) {
        openOutlook.disabled = false;
        _showConnectivityToast("Couldn't open in Outlook: " + (err?.message || err), 'warn');
      }
      return;
    }
    let url;
    try {
      const others = grid.people.filter((p) => !p.you && p.email);
      const repeating = repeat.value !== 'none';
      if (!repeating && !others.some((p) => p.optional)) {
        url = _availabilityGridComposeUrl(grid, pickedAt.di, pickedAt.k, detailValues());
      } else {
        openOutlook.disabled = true;
        openOutlook.textContent = repeating ? 'Creating the draft series…' : 'Creating the draft…';
        const slot = _availabilityGridSlotTimes(grid, pickedAt.di, pickedAt.k);
        const firstDate = repeating ? panel.first() : grid.days[pickedAt.di].date;
        ({ url } = await postGridJson('/api/calendar/grid-draft-series', {
          start: firstDate + slot.start.slice(10),
          end: firstDate + slot.end.slice(10),
          timezone: grid.timezone,
          attendees: others.filter((p) => !p.optional).map((p) => p.email),
          optional_attendees: others.filter((p) => p.optional).map((p) => p.email),
          repeat: repeating ? panel.spec() : null,
          ...detailValues(),
        }));
      }
      await launchOutlook(url);
    } catch (err) {
      if (!url) syncOutlookLink();
      else {
        openOutlook.disabled = false;
        openOutlook.textContent = 'Open in Outlook ↗';
      }
      _showConnectivityToast("Couldn't open in Outlook: " + (err?.message || err), 'warn');
    }
  });
```

(g) In the `use` click handler, append the details to the end of `reply`:

```js
        : _availabilityGridRepeatText(panel.spec(), grid.days[pickedAt.di].date, panel.first())) +
      _availabilityGridDetailsText(detailValues());
```

(h) In `addPerson`, replace the `postAvailability` call so it also asks for the zone, and store it:

```js
        const dates = grid.days.map((d) => d.date);
        const result = await postGridJson('/api/calendar/availability-days', {
          duration_minutes: grid.duration_minutes,
          emails: [email],
          dates,
          zones: true,
        });
        const days = result.days;
```

and replace the `grid.people.push(...)` line with:

```js
        const timezone = result.zones && result.zones[email];
        grid.people.push({ name: label, email, you: false, optional: false, ...(timezone ? { timezone } : {}) });
```

(i) Change the final append to place the fields above the footer: `body.append(panel.el, people, scroll, details, footer);`

(j) In `web/static/style.css`, after the `.ag-chosen` rule add:

```css
.ag-chosen-box {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.ag-zones {
  font-size: 0.75rem;
  color: var(--text-dim);
}
.ag-details {
  margin-top: 8px;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node tests/availability_grid_card.test.js && node tests/calendar_draft_card.test.js`
Expected: both exit 0.

- [ ] **Step 5: Try it in the browser**

Start the app (`dev.ps1` or the repo's normal dev start), ask the agent to "find a time with <two colleagues in different zones>", and check on the grid card:
1. Title and Message boxes sit above the footer, pre-filled when the agent supplied them.
2. Picking a slot shows one line per other zone under the chosen-slot text; adding a person via "+ Add person" gives them a zone line on the next pick.
3. Open in Outlook (one-off) opens a compose window with title and message filled in; the button reads "Opened in Outlook ↗" and is disabled; after closing the window it reads "Open in Outlook ↗", the tooltip carries the new-invite note, and a click reopens it.
4. With a repeat or an optional attendee: one draft is created; closing the window and clicking again reopens the same draft, and no second draft appears in Outlook.
5. Picking a different slot resets the button and unlocks Title and Message.
Check the browser console for errors. If the shell is not available, say so; do not claim the close signal was tested.

- [ ] **Step 6: Commit**

```bash
npx prettier --write web/static/app.js tests/availability_grid_card.test.js
git add web/static/app.js web/static/style.css tests/availability_grid_card.test.js
git commit -m "feat: availability grid shows attendee time zones, has Title and Message, and reopens Outlook after close"
```

---

### Task 6: Calendar draft card reopens after the Outlook window closes

**Files:**
- Modify: `web/static/app.js` (`openCalendarBtn` block ~12490-12546)
- Test: `tests/calendar_draft_card.test.js` (~139-141)

**Interfaces:**
- Consumes: `_watchOutlookComposeClosed(url, onClosed)` from Task 4; `config.openLabel`; `canOpenNativeApp`; `jiraEditFields`; `approveBtn`.
- Produces: after the first successful hand-off the button reopens the stored URL with no server call; Send invite stays disabled.

- [ ] **Step 1: Update the test first**

In `tests/calendar_draft_card.test.js`, replace the final assert (`gatorShell\.openOutlookCompose\(url\)` inside `openHandler`) block with:

```js
assert(/openInOutlookWindow\(url\)/.test(openHandler[0]), 'opens the popout window');
assert(!/openThirdPane/.test(openHandler[0]), 'does not load the draft into the Outlook pane');
assert(
  /async function openInOutlookWindow\(url\)\s*\{[\s\S]*?gatorShell\.openOutlookCompose\(url\)[\s\S]*?_watchOutlookComposeClosed\(url,/.test(
    source,
  ),
  'the popout is opened by one helper that also watches for it closing',
);
assert(
  /if \(handedOffUrl\)[\s\S]*?openInOutlookWindow\(handedOffUrl\)/.test(openHandler[0]),
  'a second click reopens the stored URL without asking the server for another draft',
);
assert(
  /handedOffUrl = url;/.test(openHandler[0]) && /approveBtn\.disabled = true;/.test(openHandler[0]),
  'the URL is remembered and Send invite stays locked after hand-off',
);
```

(Keep the existing `assert(openHandler, ...)` line above it unchanged. If the old `gatorShell.openOutlookCompose(url)` assert line is still present in the file, delete it; the new regex covers it.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `node tests/calendar_draft_card.test.js`
Expected: FAIL with `opens the popout window`.

- [ ] **Step 3: Implement**

In `web/static/app.js`, inside `if (openCalendarBtn) {`, add before the `openCalendarBtn.addEventListener('click', ...)` line:

```js
    let handedOffUrl = '';
    const reopenReady = () => {
      openCalendarBtn.disabled = false;
      openCalendarBtn.textContent = config.openLabel + ' ↗';
      openCalendarBtn.classList.remove('gcc-handed-off');
      openCalendarBtn.title = handedOffUrl.includes('/deeplink/compose')
        ? "Opens a new invite. If you already sent it in Outlook, don't send it again."
        : 'Opens the draft you already created in Outlook';
    };
    async function openInOutlookWindow(url) {
      if (canOpenNativeApp && window.gatorShell.openOutlookCompose) {
        await window.gatorShell.openOutlookCompose(url);
      } else {
        window.open(url, '_blank', 'noopener');
      }
      openCalendarBtn.textContent = 'Opened in Outlook ↗';
      openCalendarBtn.classList.add('gcc-handed-off');
      _watchOutlookComposeClosed(url, reopenReady);
    }
```

At the top of the click handler, before `openCalendarBtn.disabled = true;`, add:

```js
      if (handedOffUrl) {
        openCalendarBtn.disabled = true;
        try {
          await openInOutlookWindow(handedOffUrl);
        } catch (err) {
          reopenReady();
          _showConnectivityToast("Couldn't open in Outlook: " + (err?.message || err), 'warn');
        }
        return;
      }
```

Replace the block from `const { url } = await res.json();` through `openCalendarBtn.classList.add('gcc-handed-off');` with:

```js
        const { url } = await res.json();
        handedOffUrl = url;
        await openInOutlookWindow(url);
```

Leave the lines that follow (`jiraEditFields.forEach(... disabled = true)`, `approveBtn.disabled = true`, `approveBtn.classList.add('gcc-handed-off')`, the `refine` note) unchanged. In the existing `catch`, the first-click failure path keeps its current behaviour except it must not discard the stored URL: leave `openCalendarBtn.textContent = config.openLabel; openCalendarBtn.disabled = false;` as is (a later click then reopens the stored URL if the server already handed off, or asks the server again if it had not).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `node tests/calendar_draft_card.test.js && node tests/availability_grid_card.test.js`
Expected: both exit 0.

- [ ] **Step 5: Try it in the browser**

Ask the agent to draft a meeting, then on the calendar draft card: click Open in Outlook, confirm "Opened in Outlook ↗" with Send invite disabled; close the popout (Electron shell); confirm the button reads "Open in Outlook ↗", clicking it reopens the window, and Outlook shows no second draft (recurring or optional-attendee meeting). Confirm the one-off tooltip text. Without the shell (plain browser), confirm the button is usable again right after the click. Report plainly if the shell path could not be run.

- [ ] **Step 6: Commit**

```bash
npx prettier --write web/static/app.js tests/calendar_draft_card.test.js
git add web/static/app.js tests/calendar_draft_card.test.js
git commit -m "fix: the calendar draft card's Open in Outlook button works again after the Outlook window closes"
```

---

### Task 7: Full verification

**Files:** none

- [ ] **Step 1: Run the whole relevant test set**

```bash
python -m pytest web/tests tests -q -x
npm --prefix shell test
npx prettier --check web/static/app.js web/static/style.css shell/main.js shell/preload.js tests/availability_grid_card.test.js tests/calendar_draft_card.test.js tests/outlook_standalone_nav.test.js
```
Expected: all pass. Fix any failure at its cause (for example a test that counted `getSchedule` calls on the grid tool), then re-run.

- [ ] **Step 2: Spec coverage check**

Confirm each spec item maps to a passing test or a verified browser step: zones in payload (T1), add-person zones (T1, T5), slot-zones grouping/unknown/own-zone (T2), zone lines on pick (T5), Title and Message in compose URL (T4, T5), grid-draft-series subject/body (T2), "Use this time" reply (T4, T5), close IPC and preload (T3), grid reopen (T5), draft card reopen (T6), CSRF inventory (T2).

- [ ] **Step 3: Commit any fixes** with a message describing the fix; do not push unless asked.
