# AI Gator — Worktree Dev Workflow

How to test changes in the `agent-work` worktree on an isolated port, merge them
into `main`, and keep the worktree in sync afterward.

Paths used below (adjust if yours differ):

|                    | Path                                    | Branch       | Port |
| ------------------ | --------------------------------------- | ------------ | ---- |
| Main checkout      | `C:\Users\maykulka\POCs\AgenticPOC`     | `main`       | 8000 |
| Workbench worktree | `C:\Users\maykulka\POCs\AgenticPOC-dev` | `agent-work` | 8002 |

> Port 8001 is reserved for the watchdog — never point `dev.ps1` at it.

---

## 1. Spin up the main dev server (port 8000)

```powershell
cd C:\Users\maykulka\POCs\AgenticPOC
.\dev.ps1
```

Open **http://localhost:8000**.

## 2. Spin up the workbench worktree (port 8002)

```powershell
cd C:\Users\maykulka\POCs\AgenticPOC-dev
.\dev.ps1 -Port 8002
```

Open **http://localhost:8002**. Make and test your changes here — this instance
never touches the primary tray app or the 8000 server.

## 3. Merge `agent-work` into `main`

Once you're happy with what's running on 8002:

```powershell
cd C:\Users\maykulka\POCs\AgenticPOC
git merge agent-work
git push
```

## 4. Sync the worktree back to `main`

`main` may pick up other contributions besides yours (other agents/branches
merging in). After merging, reset the worktree branch to `main`'s tip so the
next round of 8002 testing starts clean and current:

```powershell
cd C:\Users\maykulka\POCs\AgenticPOC-dev
git fetch origin
git checkout agent-work
git reset --hard main
```

**Do not tear down and rebuild the worktree** — that redoes `.venv` and deps
for no reason. `reset --hard` is enough because `agent-work` is a disposable
scratch branch: once its commits land on `main`, nothing on `agent-work` is
worth preserving.

> **Gotcha:** stop the 8002 dev server before running `reset --hard`. Resetting
> while uvicorn/aider hold open file handles on changed files can behave
> unpredictably on Windows.

> If `agent-work` ever needs to carry its own long-lived, unmerged history
> (not just disposable test commits), use `git merge main` instead of
> `reset --hard main` in step 4.

---

## 5. Adding an API route that changes state

Follow this pattern for every new `POST`, `PUT`, `PATCH` or `DELETE` route.

1. Add `dependencies=[Depends(verify_csrf)]` to the route. Import `verify_csrf` from `web/security.py`. The web page sends the token in the `X-CSRF-Token` header (`window.__CSRF_TOKEN__`).
2. Do not add the route to `tests/csrf_route_baseline.txt`. That file lists old routes only, and it can only get shorter.
3. If the route sends, posts, creates or deletes in an outside app (email, Teams, Slack, Jira, calendar), make it draft-only. Create the draft in `web/skills/_drafts.py`. Send only from `/api/drafts/{id}/approve` after the user approves. Never send automatically.
4. Run `pytest tests/test_csrf_route_inventory.py`. It fails the build if a new route has no CSRF check. This is the default-deny rule for new routes.
5. In the pull request, complete the security checklist in `.github/PULL_REQUEST_TEMPLATE.md`. The reviewer checks it.
