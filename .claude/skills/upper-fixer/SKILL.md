---
name: upper-fixer
description: Run a structured, safe GitHub-issue fixing session for AI Gator. Use
  when the user wants to triage and fix open repo issues — selects issues, groups
  them, checks if any are already fixed, resolves architecture questions up front,
  keeps git history modular, and fixes with a TDD + code-review loop. Invoke directly
  (/upper-fixer) or on a check-in loop (/loop 30m /upper-fixer). Keywords — fix issues,
  triage, github issues, fixing session, batch fix, work on bugs.
metadata:
  author: maykulka
  version: "2.2.0"
  category: workflow
  tags:
  - github
  - issues
  - tdd
  - workflow
  - git
compatibility:
  universal: false
---

# upper-fixer

Orchestrate a safe, modular GitHub-issue fixing session for AI Gator
(repo `mkflyamd/AiGator`). Work through the phases **in order**. Create a
TodoWrite item per phase at the start so progress is visible.

## Guardrails (non-negotiable)
- NEVER auto-merge, auto-push, auto-comment, or auto-close. All issue comments
  are DRAFTED for explicit human approval (AI Gator human-in-the-loop rule).
- Work directly on local `main` — no worktree, no session branch. Fixes commit to
  `main` locally; the user pushes them (the skill never auto-pushes).
- Branch cleanup is MERGED-ONLY and confirmed item-by-item. Never delete unmerged work.
- One commit per issue. No `Co-Authored-By` line (project rule).
- The loop only checks in; fixing runs in the foreground with the user present.

## State
Session state lives at `.gator-session.json` in the repo root (gitignored).
See `references/session-state.md` for the schema and read/write rules.

## Risky operations & change-review (the "second opinion" gate)
Some changes are too blunt or too wide to apply on judgment alone. When a change
hits any **risk trigger** below, you MUST get a second opinion from a
change-review subagent BEFORE applying it — don't make the user adjudicate a raw
command, and don't just run it.

**Risk triggers (any one fires the gate):**
- Destructive / in-place shell mutation: `sed -i`, `perl -i`, `awk -i`, `rm`,
  `git reset --hard`, `git clean`, bulk `mv`/rename, redirect that overwrites a file.
- Global / multi-occurrence find-replace: `replace_all`, or changing a shared token
  used in many places (CSS variable, config key, shared util, env name).
- Blast radius: a single issue's diff touches **>30 changed lines** OR **more than
  one file**.
- Editing a cross-cutting / shared file: `web/static/style.css`, theme files,
  config, shared utilities, anything many modules import.

**Prefer surgical over blunt FIRST.** Before reaching for a risk-trigger command,
try the targeted tool: use Edit (not `sed -i`), scope to the specific selectors/
lines for the issue, and verify the pattern is COMPLETE (e.g. `var(--x)` with AND
without a fallback — a regex that only matches the comma form silently half-migrates).

**Change-review subagent.** When a trigger fires, dispatch a reviewer (Agent tool,
`subagent_type: feature-dev:code-reviewer`) with: the issue text + its intended
scope, the proposed diff or exact command, and these questions:
1. Is the change correctly scoped to THIS issue, or does it overreach?
2. Is the pattern/regex complete, or will it leave things half-changed?
3. Is there a more surgical alternative (Edit vs sed, scoped selector vs global swap)?
4. What is the blast radius / regression risk on shared surfaces?

It returns **APPROVE** or **REVISE (with specific reasons)**. On REVISE, fix and
re-review.

**The reviewer's verdict is the default decision-maker — don't re-ask the user
for things it can settle.** Apply this triage to its verdict:
- **Reversible & local** (a file edit, a scoped refactor, a read): an APPROVE is
  sufficient — apply it WITHOUT prompting the user. REVISE → fix and re-review.
  This is the point of the extension: stop making the user adjudicate raw
  judgment calls the reviewer can resolve.
- **Escalate to the user (with the reviewer's verdict attached, never a bare
  prompt)** in exactly three cases:
  1. **Destructive / irreversible** shell commands (`rm`, `git reset --hard`,
     `git clean`, in-place mutation) — even if the reviewer says APPROVE.
  2. **External / visible side effects** (issue comment, issue close, `git push`,
     merge) — these ALWAYS stay human per the human-in-the-loop rule; a subagent
     never authorizes them.
  3. **Genuine uncertainty** — the reviewer cannot reach a confident
     APPROVE/REVISE. Surface its doubt and let the user decide.

Out of scope for the reviewer: the harness's own permission dialogs (e.g. the
`cd`+git "untrusted hooks" Yes/No). No subagent can answer those — avoid them via
the read-only hygiene rules and settings allowlist, not by review.

Low-risk changes (a focused one-file fix under the line threshold) skip this gate
and go straight to the normal per-issue review in Phase 6.

## Park, don't block (HITL items never stall the session)
When something genuinely needs the human — a design/judgment call you shouldn't
decide alone, or an external side-effect (comment/close/push) that must stay human
— do NOT halt the session waiting on an answer. **Park it and keep moving.**

For each parked item, record it in the `parked` list in the session file with: the
issue number, the question, the options (with your lean), and any **safe default
already applied** so the issue isn't left half-done. Then continue to the next
issue. Surface ALL parked items together at Phase 8 for one batched decision.

The safe default is the YAGNI / least-surprise choice: if behavior already works
(e.g. auto-detection covers a case), do NOT add speculative API surface or scope
just because an old plan mentioned it — park that as "leaning skip" and let the
user override at wrap-up. Parking is the default for any HITL judgment call;
reserve a hard `blocked` status only for issues you genuinely cannot make progress
on at all.

## Command-shape hygiene (avoid needless approval prompts)
Triage and verification should run silently. The harness has security heuristics
that force a manual approval prompt for certain shell shapes (these OVERRIDE the
allowlist, so allowlisting `grep` won't help). These shapes get flagged regardless
of whether the command reads or writes — so the rules below apply to reads,
commits, AND test runs alike. Write commands to AVOID those shapes:

- **Use the dedicated tools, not shell pipelines:** `Grep` / `Glob` / `Read`
  instead of `grep … | head`, `ls`, `cat`, `find`. These never trip a prompt.
- **Never `cd` inside a command.** Tools run from the repo root already, which IS
  `main` — so `git add`/`git commit` work directly with no `cd` and no `-C`. The
  `cd <path> && git …` shape triggers a "may run untrusted hooks" prompt; if you
  ever must touch git in another tree, use `git -C <path> …` instead. This applies
  to ALL git, reads and writes alike — never `cd` for it.
- **No `for`-loops — ever (reads OR test runs).** A `for f in …; do …; done` (and
  the `$var` expansion / pipe inside it) can't be statically analyzed, so it ALWAYS
  forces a "shell syntax that cannot be statically analyzed" prompt, even for
  allowlisted commands. Read issues with separate `gh issue view <n>` calls or one
  `gh issue list --json …`. Run tests the same way: let the runner do the globbing
  (`python -m pytest -q`, `python -m pytest tests/<area>/`) or issue one plain
  command per file (`node tests/x.test.js`) — never loop over `tests/*.js`.
- **No compound `cd … | …` with redirection** (triggers a "path-bypass" prompt).

Net effect: a few more tool calls, but each runs without stopping for approval.

## Phase 0 — Preflight
Run these checks and report any gaps BEFORE starting work:

```bash
gh auth status 2>&1 | grep -E "Logged in|Token scopes"   # need login + 'repo' scope
git push --dry-run origin main 2>&1 | head -1            # reachability (does not push)
python -m pytest --version
ast-grep --version 2>&1 | head -1                        # blast-radius helper (Phase 6); see install hint below
```

Confirm available tools: `Agent`/`Task` (code-reviewer dispatch), `gh issue comment`,
Read/Edit/Write, `git:*`. If `repo` scope is missing or `gh` is not logged in, STOP
and tell the user how to fix before continuing. Note intentional ASK-gated prompts
(`git push`, `git branch -D`, `git reset --hard`, `git clean`) so they aren't a surprise.

If `ast-grep` is missing, print the install hint `npm i -g @ast-grep/cli` and CONTINUE — it
powers the Phase 6 blast-radius check but is non-blocking (falls back to Grep/Explore). Do NOT
auto-install it on every run, and do NOT stop the session over its absence.

## Phase 1 — Check pending work
Read `.gator-session.json` (repo root).
- If it lists issues with `status: pending` → ask the user: "Resume these N pending
  issues, or start fresh?" If resume → skip to Phase 5/6 with that selection.
- If the file is missing or `selected` is empty → go to Phase 2.

## Phase 2 — Fetch & select
List open issues:

```bash
gh issue list --state open --limit 50 --json number,title,labels,updatedAt
```

Present them to the user and AGREE on:
- which issues to tackle,
- how many,
- batch size (default 5 — NOT a hard cap),
- whether to pause for approval between batches.

Write the selection and these preferences to `.gator-session.json` (repo root;
see references/session-state.md). Do not invent issues; only use what `gh` returns.

## Phase 3 — Categorize
Group the selected issues by **subsystem + gh label** so same-area issues batch
together. Subsystem = which part of the codebase the issue touches, inferred from
the issue text and a quick grep (examples: `web/chat`, `marketplace`, `email`,
`code_runner`, `mcp`, `settings`). For large or ambiguous sets, dispatch an Explore
agent to cluster. Output a simple grouped table: subsystem | issues | labels.
Update `subsystem`/`labels` per issue in the session file.

**Non-actionable triage.** While categorizing, flag issues that aren't really
fixable as-is: duplicates, questions/support, `wontfix`, or "needs more info". Set
`status: non-actionable`, record a one-line reason, and DRAFT (don't send) a short
comment if useful (e.g. "Looks like a duplicate of #NN" / "Could you share repro
steps?"). Surface these to the user and remove them from the fix batch — don't
attempt a fix.

## Phase 3.5 — Already-fixed triage
Before fixing, confirm each selected issue isn't already resolved (agents waste
time "fixing" done work):
- **Bug issues:** write the TDD reproduction test against current `main`. If it
  PASSES immediately, the bug is already fixed.
- **Feature/UX issues:** quick code inspection (Grep/Read, or an Explore agent) to
  confirm the behavior doesn't already exist.

If already resolved → set `status: skipped-already-fixed`, remove from the fix
batch, and DRAFT (do not send) a comment: "Looks already fixed in `<area/commit>`,
proposing to close." Store it in `drafted_comments` and surface to the user for
approval. Only after explicit approval may you run `gh issue comment`/`gh issue close`.

## Phase 4 — Architecture gate
Identify issues that need a major design decision (new dependency, schema change,
cross-cutting refactor, API shape). Resolve them ALL up front so the fix loop is
never blocked later. For each, present the user a SIMPLE choice — plain language a
highschooler could follow, clear tradeoffs, invite questions. Use the
AskUserQuestion tool. Record outcomes in `architecture_decisions` in the session file.

If a decision can't be settled up front (the user isn't answering now, or it only
matters for one already-handled issue), do NOT stall — **park it** (see "Park,
don't block"): apply the safe default, record it in `parked`, and move on. A design
question attached to an already-fixed issue (e.g. "the old plan said add param X,
but auto-detect already covers it") is the classic park: skip the speculative work,
park as "leaning skip", surface at Phase 8.

## Phase 5 — Ensure clean main
Fixes are made directly on local `main` — no worktree, no session branch (this
avoids the merge-back conflicts that a drifting session branch caused).

1. Confirm you're on `main` and the working tree is clean:

```bash
git branch --show-current
git status --porcelain
```

   If not on `main`, switch to it. If the working tree has unrelated uncommitted
   changes, STOP and ask the user — never discard their work.

2. Bring `main` up to date so fixes aren't built on stale code:

```bash
git pull --ff-only
```

   If the pull can't fast-forward, stop and ask the user rather than forcing it.

3. **Optional merged-only cleanup.** Old `session/*` branches from previous runs
   can be removed, with confirmation, ONLY if already merged:

```bash
git branch --merged main | grep -vE "^\*|main|public"   # candidates only
```

   For each candidate: show it, ask the user to confirm, then `git branch -d <name>`.
   NEVER delete unmerged branches or use `-D`/`--force` without explicit instruction.

## Phase 6 — Fix in batches
Process issues in batches of the agreed size. Invoke
superpowers:test-driven-development. For EACH issue:
1. Write a failing pytest test reproducing the issue. Re-confirm it FAILS on
   current code (`python -m pytest <path>::<test> -v`). If it passes, route back to
   Phase 3.5 (already fixed).
2. Plan the fix as the most surgical change possible. **If the change hits any risk
   trigger, run the change-review gate first** (see "Risky operations &
   change-review"): get an APPROVE from the change-review subagent before applying.
   Prefer Edit over `sed -i`; verify patterns are complete.
3. Implement the minimal fix. Dispatch agents/other skills as needed.
4. **Regression check.** First **map the blast radius**: if the fix changed a
   function/method/symbol, find its real call sites with ast-grep (AST-precise,
   not text grep) — e.g. `ast-grep run -p 'changed_symbol($$$)' -l py web/`
   (swap `changed_symbol` for the actual name; `$$$` matches any args). Use the
   caller list to choose which tests/subsystems to exercise: if callers live in
   areas the new reproduction test does not cover, widen the run before
   committing. If `ast-grep` is unavailable, fall back to Grep/Explore. Then run
   the new test AND a broader run to catch breakage the
   fix may have caused elsewhere: the touched subsystem's test folder, and the full
   suite if it's reasonably fast (`python -m pytest -q`). If the fix reddens
   UNRELATED tests, STOP — don't commit. Fix the regression or revert and re-think.
   Keep the reproduction test — it is committed WITH the fix as a permanent
   regression guard, never deleted.
5. Dispatch the **code-reviewer agent** (Agent tool, subagent_type
   feature-dev:code-reviewer). In its brief, explicitly ask it to flag: blunt-
   instrument edits, incomplete regex/patterns that half-migrate, changes wider
   than the issue's blast radius, and missing fallbacks on shared tokens. Address
   findings.
6. Commit directly to local `main` — one modular commit per issue (including its
   regression test), message referencing the issue number (e.g.
   `fix(code_runner): ... (#76)`). Stage and commit with `git add <files>` then
   `git commit -m "…"` (you're already at repo root on `main` — no `cd`, no `-C`).
   NO `Co-Authored-By` line. Do NOT push (the user pushes). Set `status: fixed` in
   the session file.

**If an issue can't be fixed** (too hard, ambiguous, needs info you don't have):
don't get stuck. Set `status: blocked` with a one-line reason, optionally DRAFT (not
send) a clarifying comment for the user to approve, and move on to the next issue.

After each batch: print a summary (fixed / skipped-already-fixed / non-actionable /
blocked / remaining). If `pause_between_batches` is true, STOP and wait for the
user's go-ahead.

## Phase 7 — Verify & close each issue
Goal: confirm each fix actually works, then close the issue with a paper trail.
For EACH issue with `status: fixed`:

1. **Suggest a simple test.** Write a short, plain-language way to check the fix —
   the kind a highschooler could follow. Pick the form that fits the issue:
   - the pytest command that now passes (`python -m pytest <path>::<test> -v`), and/or
   - a 2–4 step manual prompt ("open Settings → switch to light theme → the Persona
     box should be readable"). Keep it concrete and short.
   Store it as `test_hint` on the issue in the session file and show it to the user.
2. **Verify.** Run the automated test if there is one. For UI/UX issues, ask the
   user to run the manual steps and confirm, or use the `verify` skill to drive the
   app. Do not claim it works without evidence.
3. **Draft the closure comment (NEVER auto-send).** Once verified, draft a comment
   that references the paper trail:
   - the **commit id**(s) that fixed it (e.g. `Fixed in 120f148`), and
   - the **PR link** if a PR exists for this work (`gh pr view --json url` / the PR
     number). If no PR, the commit id alone is fine.
   Include the one-line test_hint so a reviewer can re-verify.
   Example draft: "Fixed in `120f148` (PR #NN). Verified by: <test_hint>."
   Store it in `drafted_comments`.
4. **Get approval, then close.** Present the drafted comment to the user. ONLY after
   explicit approval, run `gh issue comment <n> --body "..."` then, if the user
   agrees to close, `gh issue close <n>`. Set `status: closed` in the session file.
   If the user declines, leave the issue open and keep the draft.

## Phase 8 — Wrap up
Finalize `.gator-session.json` (statuses, test hints, drafted comments, closures,
architecture decisions, parked items). **Resolve parked items here:** present the
`parked` list as one batched set of decisions (each with its question, options, your
lean, and the safe default already applied), and let the user accept the defaults or
override. Print a closing summary: what's fixed, what's verified, what's closed,
what's parked awaiting a decision, what remains, any drafted comments still awaiting approval, and the
list of fix commits now on local `main`. Do NOT auto-push — present pushing `main`
as an explicit user-confirmed next step.
