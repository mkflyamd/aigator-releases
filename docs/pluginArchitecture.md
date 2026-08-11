# AI Gator — Plugin Architecture

> **Authoritative section:** [2026-08-07 Milestone — Plugin Marketplace (A + B + E)](#2026-08-07-milestone--plugin-marketplace-a--b--e).
> Everything below that section under "Historical design notes" predates this milestone and is **superseded** where it conflicts. Read the milestone section first.

**Naming convention:**
- "Skill" — user-facing term (what users see in the UI)
- "Plugin" — internal term used in code and file structures
- A marketplace **plugin** may *bundle* multiple skills (see decision #3).

---

## 2026-08-07 Milestone — Plugin Marketplace (A + B + E)

### What we're building (one sentence)

Render Anthropic's `claude-plugins-official` marketplace inside AI Gator's "Skills and Plugins" settings, and let users **one-click install** the **non-coding** plugins (skills + MCP-server integrations + minimal commands) into Gator chat, with a consent gate before any third-party code runs — while pointing users at the **Coding Agent (OpenCode)** for coding-oriented plugins.

### Why we're building it — and why the value is *narrower* than "plugin support"

This was interrogated hard before committing. The honest conclusion:

- **The marketplace delivers *discovery + one-click preconfigured install + guided secret entry* — NOT new capability.** AI Gator already has a full MCP layer with a manual "Connect an MCP server" modal (shipped 2026-05-19) and already has a skill system. A user can already add any of these integrations by hand. The marketplace makes ~280 curated integrations *browsable and one-click* instead of hand-configured.
- **The value scales with a non-technical audience.** User confirmed the chat surface has **mixed / non-developer** users, who will not hand-edit MCP JSON. Guided one-click install is therefore genuinely valuable here (it would be marginal for an all-engineer audience).
- **Coherence with OpenCode.** OpenCode is deeply integrated and owns *coding*. To avoid three competing extension surfaces (OpenCode plugins, Gator's manual MCP tab, this marketplace), the product line is drawn deliberately: **Gator chat = hub for non-coding service integrations; OpenCode = home for coding.** Coding plugins are redirected to the Coding Agent (decision #8), not installed into chat.

### Why we did NOT lift an implementation from open source

Investigated directly, not assumed:
- **OpenCode** (`anomalyco/opencode`): its "plugins" are JS/TS modules that hook OpenCode's *own* TUI (`tool.execute.before`, `session.created`, …). No marketplace ingestion, no install-from-catalog, no MCP-on-behalf-of-a-plugin. Different problem. Confirmed from its docs and a repo clone.
- **Official MCP Python SDK** (`modelcontextprotocol/python-sdk`): explicitly does *not* handle marketplaces/catalogs/installation. It's the protocol runtime only — and AI Gator **already wraps it** (`mcp>=1.27.2`) for HTTP/SSE, plus a hand-rolled stdio client. Right layer for E, wrong layer for the marketplace.
- **Claude Code CLI**: it *is* the reference implementation, but ships closed/minified — no source to lift.

**Conclusion:** the marketplace↔host adapter is inherently bespoke (it's the seam between Anthropic's catalog format and *our* install/run model; the "where does it run" half differs per host, so no reusable library spans it). Everything reusable (MCP runtime, HTTPS-tarball installer, catalog cache, uninstall, provenance ranking) is *already in the tree* and is reused. The genuinely new code is: the catalog fetcher (A), plugin.json parse + recursive skill-bundle registration + versioned install + consent dialog + coding classifier (B), and plugin-MCP → connection-record mapping (E).

### Capability data (why A+B+E ≈ 90% coverage)

Measured 2026-08-07 against the live 280-plugin catalog (metadata on all 280; folder inventory on 54 local Anthropic-curated; stratified GitHub-tree sample of 38 remote):

| Capability | Local 54 | Remote sample |
|---|---:|---:|
| skills (`SKILL.md`) | 33% | **94%** |
| mcp (`.mcp.json` / `mcpServers`) | 27% | 48% |
| commands | 26% | 8% |
| agents | 15% | 10% |
| hooks | 11% | 16% |
| lsp | 22% (12 `*-lsp`) | 0% |

- **A+B+E coverage ≈ 90%+** of the catalog installs and delivers primary value (skills nearly universal; MCP ~half; both handled).
- Integration plugins ship **both** a thin `SKILL.md` *and* an `.mcp.json` — which is exactly why **B and E are co-required**: B-without-E on an integration plugin gives prompt guidance referencing tools that don't exist.
- Remaining gaps are bounded: **12 LSP plugins** (→ coding redirect, decision #8), and a **handful of pure agents/hooks-only plugins** (→ deferred C/D). Plugins that ship agents/hooks *alongside* skills/mcp install their primary value and show the extras as "coming soon" (honest-partial).

### Locked decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Scope = A (browse) + B (skills + *minimal* commands) + E (MCP).** | Highest-coverage, coherent milestone. |
| 2 | All `claude-plugins-official` entries → **Verified** tier; render the **full catalog** (all 280). | Inclusion in Anthropic's curated marketplace *is* the "Verified" bar for this milestone. "Verified" ≠ AMD-reviewed — hence the consent gate (#7). Full catalog per user direction; coding ones get redirected, not hidden (#8). |
| 3 | **A plugin is a bundle.** Recurse `skills/*/SKILL.md`; one versioned install record; one catalog card ("AMD Skills — 7 skills"); uninstall removes all. | Real data: `amd-skills` = 1 entry → 7 skills. A naive single-`SKILL.md` assumption installs zero skills for such plugins. |
| 4 | **Install = reuse HTTPS-tarball fetcher** (`web/marketplace/github_fetcher.download_skill_tarball`, `codeload.github.com/.../tar.gz`) at the **pinned `sha`**; **no git**. | Fetcher already exists (subdir extraction + size/file-count/symlink/traversal caps). git is not bundled and buys nothing. 227/280 entries pin a sha → reproducible installs (matches Claude Code). |
| 5 | **MCP credentials = reuse `mcp_connections`** (in `config.json`) + the add-modal's existing `{placeholder}`-field flow for stdio `env` secrets; existing auth UI (none/bearer/api_key/basic/oauth2) for HTTP servers. | Auth model + UI already exist. Only real gap: no *manual* env-var editor — but declared env vars map cleanly onto the existing placeholder-field mechanism. No new auth subsystem. |
| 6 | **Runtime: node-based MCP works out of the box; python/`uvx` degrades gracefully with the existing "install uv" hint; do NOT bundle `uv` for v1.** | Node is bundled (`web/proc_utils.ensure_bundled_node_on_path`) → `npx` servers just run (the majority). `uv` bundling adds build/packaging scope for a minority; revisit on telemetry. |
| 7 | **Consent gate at install** (new — before any third-party code runs). Dialog names what will execute (e.g. "runs a local server via `npx @vendor/mcp` — can execute code on your machine"), lists declared capabilities, requires explicit Install; consent stored on the install record (no per-turn nagging). | Today there is **zero** consent gate — adding an MCP connection immediately spawns it. A one-click marketplace turns that into arbitrary remote code execution. Non-negotiable. Consistent with the project's existing consent-first posture (HITL never-auto-send). |
| 8 | **Coding redirect** (new): full catalog shown, but **LSP plugins (12) are not installable in chat** — they render as **"Use the Coding Agent"** (this also resolves deferred Phase L). Other **repo-acting** coding plugins (code-review, feature-dev, pr-review-toolkit, code-modernization, …) show an **advisory banner** pointing to the Coding Agent but **remain installable**. Everything else installs normally. Classification is **advisory, not category-blocking**. | OpenCode owns coding; don't make chat a second coding-extension surface. **But** `category:"development"` is a noisy signal — e.g. `amd-skills` is `development` yet belongs in chat — so a hard category block would bounce our own motivating example. LSP is the only unambiguous hard case (it literally can't render in a chat app). The redirect is currently **informational**; auto-provisioning a plugin into OpenCode is out of scope (possible fast-follow). |
| 9 | **Uninstall = yes** (extend `web/marketplace/installer.uninstall_skill` to also cover `PLUGINS_DIR/cache` **and** tear down the plugin's `mcp_connections` entry + stop its process). **Update = deferred** ("Phase U"); interim update path = uninstall + reinstall. | Installing without a clean uninstall is a trap. Update (re-fetch newer sha, re-consent on capability change, migrate) is materially more complex and low-urgency. |
| 10 | **Name collisions = show both** (tier badges disambiguate); coexist via the versioned `cache/{marketplace}/{id}/{version}` path; on a runtime skill-id clash, **prompt "already installed from another source — replace?"** — never silently clobber. | `frontend-design` exists in both `anthropics/skills` (Community) and `claude-plugins-official` (Verified). Provenance ranking already decides which wins at runtime. |
| 11 | **Commands = minimal.** Register `commands/*.md`; support user-typed `/command args` with `$ARGUMENTS` + positional (`$1`,`$2`) substitution → inject the expanded body as the user turn; its **own** registry, not shoehorned into skills. | Gator's existing `/plugin:capability` router is skill-*activation*, not a parameterized prompt-template runtime — so commands need a small new path regardless. But the `/name` parsing seam makes it ~a day, not a subsystem. |
| 11a | **Commands — deferred sub-features:** `allowed-tools` enforcement, per-command `model` override, inline `!bash` execution, `@file` references. | Long tail; a plugin's command works for the common case without them, and faking them is worse than deferring honestly. |
| 12 | **Command discovery UI (Increment 4):** wire installed plugin commands into the existing "/" compose-bar dropdown (`_openSkillPickerDropdown` / `SKILL_REGISTRY` in `app.js`) — new endpoint exposing `COMMAND_REGISTRY`, injected the same way `__USER_SKILLS__` already is, rendered as a second "COMMANDS" section in the existing dropdown. | Without this, an installed plugin's commands are usable (Increment 2's backend works) but **undiscoverable** — a user must already know the exact command name to type it blind, since AI Gator's existing `/` dropdown only lists `SKILL_REGISTRY`, with zero knowledge of `commands.py`. Cheap to add — reuses the entire existing dropdown/filter/keyboard-nav mechanism, only needs a second data source. |

### Deferred / explicitly NOT building in this milestone

| Item | Status | Why deferred |
|---|---|---|
| **Phase L — LSP loader** | Deferred; **subsumed by decision #8** (LSP → "Use the Coding Agent"). | LSP value renders in a code editor; Gator chat has no editor surface. Building one is its own project. |
| **Phase C — Agents loader** (`agents/`) | Deferred | Long-tail (~10–14%); almost always shipped *alongside* skills/mcp, so honest-partial covers the plugin's primary value. Gator-specific agent-run semantics = new work. |
| **Phase D — Hooks loader** (`hooks/`) | Deferred | Long-tail (~10%); highest systemic blast-radius (a bad hook degrades Gator generally). Partial seam exists in `web/hooks/executor.py`. |
| **Plugin update ("Phase U")** | Deferred | See decision #9. Interim = uninstall + reinstall. |
| **Bundling `uv`/`uvx`** | Deferred | See decision #6. Node covers the majority. |
| **Custom / third-party marketplaces ("Phase F")** | Deferred | One hard-coded marketplace (`claude-plugins-official`) only. BYO-marketplace = signing/supply-chain/takedowns; customer-gated. |
| **Advanced command features** | Deferred | See decision #11a. |
| **Auto-provisioning coding plugins into OpenCode** | Deferred | The coding redirect (#8) is informational for now. |

### Where each piece lands in the codebase (reuse vs. new)

| Concern | File(s) | New or reuse |
|---|---|---|
| A — catalog fetch (`marketplace.json` → catalog entries, Verified tier) | `web/marketplace/registry.py` | **New** fetcher; slots into existing `refresh_catalog()` 6h merge + `/api/marketplace/catalog`. |
| B — install (tarball @ sha → `PLUGINS_DIR/cache/{mp}/{id}/{ver}`) | `web/marketplace/installer.py`, `web/marketplace/github_fetcher.py` | **Reuse** `download_skill_tarball` (add `sha` ref); **new** plugin-install path + record. |
| B — manifest parse + recursive skill-bundle registration | `web/marketplace/loader.py`, `web/shared.py` (`load_installed_skill_prompts`) | **New** recursion over `skills/*/SKILL.md`; reuse tool hot-load. |
| B — coding classifier (LSP hard / repo-acting advisory) | `web/marketplace/registry.py` (or a small helper) | **New**, lightweight/advisory. |
| B — consent gate + install/consent dialog | `web/static/marketplace-pane.js`, `web/routes/marketplace.py` | **New** UI + a `consented` field on the install record. |
| E — plugin MCP server → `mcp_connections` entry + env placeholders | `web/mcp/manager.py`, `web/static/mcp_add_modal.js` (placeholder flow) | **Reuse** connection model + spawn + tool registration; **new** mapping from plugin's declared server to a connection record. |
| Commands (minimal) | `web/routes/chat.py` (`parse_slash_command` seam) | **New** small command registry + `$ARGUMENTS` substitution. |
| Uninstall (plugins + MCP teardown) | `web/marketplace/installer.py`, `web/mcp/manager.py` | **Extend** `uninstall_skill`; reuse MCP `release_from_pool`. |

> Verified facts backing the above (2026-08-07): install is HTTPS-tarball, **not** git; node bundled, uv/python-for-plugins not; MCP connections persist in `config.json:mcp_connections` and already support stdio `env`; there is **no** existing consent gate; `_MAX_AUTO_SKILLS=4` provenance cap already exists; `uninstall_skill` covers `INSTALLED_SKILLS_DIR` but not `PLUGINS_DIR/cache`.

---

### Implementation log

Built as reviewed increments — Sonnet implements, Opus adversarially reviews (4 parallel finder angles: correctness × 2, cross-file impact, cleanup/test-adequacy; each verified independently at the code level, not taken on the implementer's report alone), fixes dispatched back before commit.

#### Increment 1 (commit `a2b3950`) — Phase A + B backend
Catalog fetcher (`registry.fetch_claude_plugins_official`), `classify_coding()`, plugin-bundle install core (`installer.install_claude_plugins_official_plugin`), recursive skill discovery, uninstall extension. **`marketplace_claude_plugins_official_enabled` defaults `False`** — deliberately, so entries don't surface in the live catalog until the install route (Increment 2) exists to handle them correctly.

Adversarial review found and fixed before commit:
- Catalog-flag-on-by-default would have let the *existing* install route corrupt-install these entries (writes GitHub HTML as SKILL.md) — flag flipped to default-off.
- **Skill-id collision**: bundled skills were keyed by bare parent-folder name; two plugins sharing a skill-folder name (or a plugin whose SKILL.md sits at the version root) silently collided/mis-registered. Fixed with `namespaced_skill_id()` / `skill_id_for_cache_path()` — one function, called identically by the writer (`installer.py`) and every reader (`shared.py`, `code_runner/tools.py`) so they can't drift apart.
- Verified-tier vs. Community-tier merge order (decision #10 intent) was backwards — fixed by ordering the Verified source first in `refresh_catalog`.
- `{source:"github", repo, commit}` shape (no `url` key — real entries: `fullstory`, `jfrog`) was silently unparseable — fixed.
- Stale-sha-on-skip when re-registering an already-installed version — fixed (reuse the existing record, never re-upsert a diverged sha).
- Cleanup: extracted `_write_files_atomically()` shared by both tarball-install call sites.

#### Increment 2 (commit `b291c48`) — install route wiring, consent enforcement, commands runtime
- **Install routing**: `POST /api/marketplace/install` now looks up the entry server-side from the cached catalog (`_find_catalog_entry`, never trusts a client-supplied `source`) and routes `source=="claude-plugins-official"` entries to the real plugin installer instead of the corrupt-install fallback.
- **Consent gate (decision #7), server-enforced**: without `consent=true` in the request, the route fetches (read-only, zero disk writes) and returns the plugin's declared capabilities (`skill_count`/`has_mcp`/`has_local_code`) so a future dialog can render an accurate prompt — nothing installs. `coding_class=="coding_hard"` (LSP) is refused **regardless of consent** (decision #8), HTTP 403.
- **Minimal commands (decision #11)**: new `web/marketplace/commands.py` — its own registry (deliberately not folded into `SKILL_PROMPTS`), `commands/*.md` discovered/registered at install, `/command args` expands `$ARGUMENTS`/`$1`/`$2`/... into the template body before the existing `/plugin:capability` parsing in `chat.py`. Advanced command features (`allowed-tools`, per-command model override, `!bash`, `@file`) remain deferred per #11a.
- **Uninstall teardown seam**: `_teardown_plugin_mcp()` — a no-op today, called unconditionally from the plugin-bundle uninstall branch, with a test asserting it's called — so Increment 3 (Phase E) can fill in the real MCP-connection teardown without another refactor of `uninstall_skill`.

Adversarial review found and fixed before commit:
- **TOCTOU on consent**: the no-consent preview and the consent=true install each independently re-fetched the plugin from GitHub — for the ~53/280 entries with no pinned sha, upstream could change content between the two calls, so the user's consent wouldn't cover what actually got installed. Fixed: the preview response carries the exact `resolved_ref` it fetched; the install call accepts a `pinned_ref` and, when given, fetches that exact ref instead of re-resolving — closing the gap between "what you approved" and "what runs."
- **Command-template substitution bug**: `$ARGUMENTS` was substituted first, then a second regex pass scanned the *already-substituted* string for `$1`/`$2`/... — so a user argument containing a literal `$150` (or any `$<digits>`) got mangled as if it were a template placeholder. Fixed: single-pass substitution against the original template body only; replacement text is never re-scanned.
- `installable` check defaulted fail-*open* (`.get("installable", True)`) — a stale/malformed catalog entry missing the field would have skipped the hard LSP block. Fixed to fail-closed (`False`).
- Command names had no collision guard against existing skill ids — a plugin command named e.g. `rocm-basics` would have hijacked the model's own bare-`/skillname` auto-activation for a same-named skill. Fixed: `register_plugin_commands` skips (logs, doesn't raise) any name already in `shared.SKILL_PROMPTS`.
- Same sha-divergence bug class as Increment 1's fixed finding, reintroduced in the sibling "version dir exists, no install record" fallback branch — fixed the same way (don't record a sha you can't verify against what's actually on disk).
- Cleanup: `commands._parse_command_md` now reuses `registry._parse_skill_md_frontmatter` instead of re-deriving the same frontmatter loop.

**Open items surfaced by review, explicitly not resolved yet — carried forward:**
- **Scope-boundary question (needs a product decision, not a code fix):** the consent/`coding_hard` gate only fires for entries reached via the catalog (`source=="claude-plugins-official"`). The pre-existing `install_url`/GitHub-tree import path (`_install_github_folder`, untouched by this milestone) has no equivalent check and could install the same LSP/MCP content by URL — consistent with that path's original design ("Community tier, unverified, runtime sandbox bears the trust burden"), but worth an explicit decision on whether that boundary is intended to stay narrower than decision #7's "before any third-party code runs" language suggests.
- **Increment 4 must-do, not yet built:** the *existing* `web/static/marketplace-pane.js` doesn't handle any of the new response shapes — a 200 `{ok:false, consent_required:true}` reads as success in `_importInstall`; `_install`'s generic error branch has no `consent_required`/`capabilities` handling and no `detail`-is-an-object handling for the 403. Increment 4 must build dedicated UI for these, not assume the generic install-button code path works unchanged.
- Command names remain globally unnamespaced across plugins (last-installed wins on a same-named command from two different plugins) — accepted per decision #11a's "long tail, deferred" framing, not a namespacing scheme like skills got in Increment 1.
- No escape syntax for a literal `$<digits>` in a command template with zero arguments typed — resolves to empty string (same rule as a missing positional argument), documented as a known limitation rather than fixed with new escape syntax.

#### Increment 3 (commit `e72094d`, Phase E) — plugin-bundled MCP servers, backend only, still no frontend UI
- **Registration (`web/marketplace/installer._register_plugin_mcp_servers`)**: parses a plugin's `.mcp.json` (root manifest, alongside `.claude-plugin/plugin.json` — the canonical Claude Code location — merged with any bundled skill dir's own `.mcp.json`, root winning a same-named collision) with `mcp.normalizer._parse_server_entry` — the **same parser** the manual "Connect an MCP server" add-modal uses, so a plugin's declared server is interpreted with exactly the schema Claude Code itself uses, not a bespoke one. Called from `install_claude_plugins_official_plugin` right after skill/command registration.
- **Connection model (`web/mcp/manager.register_plugin_mcp_server` / `remove_plugin_mcp_servers`, new)**: each declared server maps onto the *existing* `mcp_connections` record shape (decision #5 — no new mechanism), keyed by a deterministic id `plugin:{plugin_id}:{server_name}` and tagged with an explicit `plugin_id` field (belt-and-suspenders — teardown matches on either). A self-contained server (no unresolved `{PLACEHOLDER}` in its declared env/headers/url) is registered by delegating straight to `add_or_update()` with `connection_id` pinned to the deterministic id — going through the **exact** live-connect/tool-discovery/PATH-resolution path (`stdio_client.ensure_bundled_node_on_path`, decision #6) a manually-added connection uses, then tagged with `plugin_id` after the fact (`add_or_update` has no param for arbitrary extra record fields). A server declaring an unresolved secret is persisted **disabled**, with empty `cached_tools` and a `missing_secrets` list, and is never spawned. A server whose live connect fails (command not found, network error, etc.) is likewise persisted disabled with a `connect_error` field — one broken MCP server must not fail the whole plugin install.
- **Teardown (`installer._teardown_plugin_mcp`, filling in Increment 2's seam)**: delegates to `mcp.manager.remove_plugin_mcp_servers(plugin_id)`, which finds every connection owned by that plugin and calls the **same** `mcp.manager.remove()` a user-initiated single-connection delete uses per connection — process release from the stdio pool, namespaced-tool deregistration, config persistence, and OAuth-credential wipe all reused verbatim, not reimplemented.
- **Consent-data extension (`get_claude_plugins_official_capabilities`, `routes/marketplace.py`)**: when `has_mcp` is true, the response now also carries `mcp_servers: [{name, needs_secrets}]` — computed read-only from the in-memory fetched tree (`_discover_plugin_mcp_manifest_from_files`, the same merge/parse logic as the on-disk registration path, just over `{relpath: bytes}` instead of a written plugin dir) — so Increment 4's consent dialog can say "needs a Datadog API key" instead of just "runs a local server" without another backend round-trip.
- **Install record**: `mcp_connection_ids` (plugin-bundle-only field, same optional-kwarg pattern as `skill_ids`/`command_ids`) persists every connection id the plugin registered, whether enabled or pending.

Judgment calls made (no existing precedent to follow):
- **"Pending/needs-config" connection state**: `mcp_connections` had no prior concept of a not-yet-usable connection. Chose the already-load-bearing `enabled: false` (already respected by `load_all_from_cache`, `list_with_status`) plus two new record fields — `missing_secrets` (unresolved placeholder names) and `connect_error` (a failed live-connect attempt) — rather than inventing a separate status enum. Increment 4 (secret-collection dialog) is expected to fill in the missing env value, flip `enabled: true`, and re-probe — likely by calling `add_or_update` with the completed env and the same pinned `connection_id`.
- **`.mcp.json` scope**: the milestone doc doesn't pin down whether a plugin's manifest lives at the plugin root or per bundled-skill dir. Chose **both**, merged, root winning ties — matches real Claude Code plugins (root, next to `.claude-plugin/plugin.json`) while still tolerating the per-skill convention `marketplace.loader.load_plugin_mcp` already uses for the separate single-skill install path.
- **Placeholder detection**: reused `mcp.normalizer._find_placeholders` (originally written for the add-modal's own `{VAR}`-in-headers detection) rather than writing a second regex — it already matches both `{VAR}` and `${VAR}` shapes.

Adversarial review found and fixed before commit (3 parallel finder angles — correctness on the manager/secret-detection side, cross-file/install-flow impact, cleanup/test-adequacy — each fix independently re-verified at the code level, not taken on the implementer's report alone):
- **Secret detection missed a whole class of secrets**: `_missing_secrets_for_server` originally only scanned declared `env` values for `{PLACEHOLDER}` syntax. Two real gaps fixed: (1) a secret passed as a CLI arg (`{"args": [..., "--api-key", "{FOO_API_KEY}"]}`) went completely undetected and would have been live-spawned with the literal placeholder string as an argument — now `args`/`command` are scanned too via the same `_find_placeholders` helper; (2) the common "empty string means fill this in" convention (`"env": {"API_KEY": ""}`, no template syntax at all) was invisible to the placeholder regex — now checked as an independent condition layered on top, without changing `_find_placeholders`' own semantics (it has another caller with different needs).
- **Consent-preview and real-install `.mcp.json` discovery scanned different scopes** — the exact "what you consented to isn't what happens" class of bug this milestone already fixed once (Increment 2's `pinned_ref` TOCTOU fix). The read-only preview scanned *every* `.mcp.json` anywhere in the tarball; the real install only scanned the plugin root + bundled skill dirs. Fixed by deriving the same skill-dir scope from the in-memory tree (`_discover_bundled_skill_dirs_from_files`) so both paths see identical servers.
- **Synchronous live MCP spawn with no bounded timeout** could hang an install HTTP request for 30–120+ seconds on a slow first-run `npx` fetch (30s per-RPC timeout, no overall connect deadline). Fixed: the connect attempt now runs under an explicit ~60s overall timeout; a timeout is treated as an ordinary connect failure (disabled connection + `connect_error`), not a hang.
- **Partial teardown on exception could orphan a connection forever**: `remove_plugin_mcp_servers`'s removal loop had no per-connection isolation — one failure aborted the rest, and since `uninstall_skill` deletes the plugin's cache dir + install record unconditionally afterward, an un-removed connection would lose the only record that could ever re-target it for cleanup. Fixed: each `remove()` call is now isolated in its own try/except; failures are logged by specific connection id and the function returns only the ids that actually succeeded.
- **Already-installed fast path never registered MCP for pre-Phase-E plugins**: a plugin installed by Increment 1/2's code (before this increment existed) would never get its `.mcp.json` wired up short of a full uninstall+reinstall. Fixed: the fast path now backfills registration when the existing record has no `mcp_connection_ids` key at all (distinct from "has the key with an empty list," which means Phase E already correctly found zero servers).
- **Unescaped `:` in connection ids could collide across plugins**: `server_name` is an arbitrary key set by any third-party plugin author and could contain a colon, letting two different (plugin, server) pairs produce the identical `plugin:{id}:{name}` connection id — silent overwrite, and cross-plugin teardown via the prefix-match fallback. Fixed with `_escape_id_part()`, applied identically at both the id-construction site and the removal-matching site (verified these two can't drift apart, since a mismatch there would silently break ownership matching).
- **Duplicated disabled-connection-record construction had already drifted**: the code paths for "missing secrets" and "connect failed" each built their own version of the disabled-connection dict, and the connect-failure/http-transport one had already dropped `auth_type`/`auth_value`/`extra_headers` that the other path and `add_or_update` itself always set. Fixed by extracting one shared builder used by all three disabled-connection cases (missing-secrets, connect-error, timeout).
- Narrow TOCTOU between `add_or_update`'s own save and the follow-up save that stamps `plugin_id` onto the record: a concurrent removal in between could delete the connection, and the stamp step would silently no-op while the function still reported success. Fixed to report failure if the record is gone by the time of the stamp step.

Explicit TODOs for Increment 4 (not built here):
- Frontend consent dialog rendering `mcp_servers`/`needs_secrets` (`web/static/marketplace-pane.js` still doesn't handle any of Increment 2's new response shapes either — see that increment's open items above).
- A secret-collection UI + endpoint that fills in a pending connection's placeholder env value, flips `enabled: true`, and re-probes/registers tools — today a pending connection stays pending forever with no code path to complete it.
- Surfacing `plugin_id`-owned connections distinctly in the existing MCP connections settings list (e.g. "Postgres MCP — from postgres-mcp plugin") — the data (`plugin_id` field) is there; `list_with_status()` doesn't yet expose it.
- The `web/marketplace/loader.py` `load_plugin_mcp`/`mcp.manager.register_plugin_servers` TODO path is a second, independent MCP-registration mechanism for the same `.mcp.json` schema (used by the older single-skill install flow) — currently inert (the function it needs doesn't exist, caught by `ImportError`), so no double-registration risk today, but a landmine for whoever eventually implements that TODO without reconciling it against this increment's `plugin:{id}:{name}` connection model.

#### Increment 4a (commit `7997372`) — core install-flow frontend

Split from a single "Increment 4" because it's the whole frontend surface; 4a is what's required to safely flip the catalog flag on, 4b (secret-collection UI, command discovery per decision #12) is completeness, not a blocker.

- **Catalog cards**: `claude-plugins-official` entries render in the existing Browse tab, tier-badged **Verified** (with the tooltip corrected — it previously said "Reviewed by your admin," which was actively wrong per decision #2 and undermined the whole point of the consent gate).
- **Coding redirect (decision #8)**: a single `_cardActionState(skill, isInstalled)` function is the one place that decides a card's button — `coding_hard` (LSP) renders a disabled "Use the Coding Agent" button with no click-through to consent at all; `coding_soft` shows an advisory line but stays fully installable; everything else installs normally.
- **Consent dialog (decision #7)**: clicking Install fires the existing no-consent preview call first (nothing installed), renders what it returns (skill count, `has_local_code`, `mcp_servers` + `needs_secrets`), and only on explicit confirm fires the real install with `consent: true` **and** `pinned_ref` echoed from the preview's `resolved_ref` — required, not optional, or the client-side flow would reintroduce the TOCTOU gap Increment 2 already closed server-side.
- **Collision prompt (decision #10)**: a client-side best-effort check (`_findCollisionEntry`) flags when the same catalog id is already installed from a different source and prompts "Replace & Install"; known limitation — this only catches a top-level id match, not a collision inside a multi-skill bundle's namespaced sub-skill ids (would need a new backend endpoint to resolve pre-install, out of scope here).
- **Fixed the two pre-existing response-handling bugs** flagged as an Increment-4 must-do since Increment 2: `_importInstall` was treating any HTTP 200 as success even when the body was `{ok:false, consent_required:true}`; the generic error handler was string-concatenating an object `detail` (the 403 shape) into `"[object Object]"`. Both fixed via a shared `_errorMessage()` helper, now reused everywhere in the file that used to hand-roll `data.detail || data.error || 'Unknown error'`.

Verification: this was the first UI-facing increment, so it was live-tested against the **real 284-entry catalog** on an isolated dev instance (a separate workbench server, not the primary session) with the feature flag temporarily flipped locally (reverted after) — confirmed all `coding_hard`/`coding_soft` entries render correctly, ran a real end-to-end install (`code-modernization`: consent dialog → real GitHub fetch → success → appeared in Installed) and uninstall, and confirmed no server errors. That live pass caught two real bugs no code review had: Native/Verified id sharing (`github`, `slack` are both Native *and* real Verified plugin ids) breaking the collision check, and the generic installed-id set being source-blind (making the collision prompt dead code for a real case — `skill-creator` exists as both Community and Verified in this environment).

Adversarial review found and fixed before commit:
- **No busy-state guard — real concurrency risk, not just a UX nit**: neither the card's Install button nor the modal's confirm button was disabled during the flow, unlike the file's own established `_importInstall` convention. A double-click (or just the preview fetch taking a few seconds) could fire two concurrent flows, stack two consent modals, and — if both were confirmed — race two `consent:true` installs on the same deterministic MCP connection id in the Increment 3 backend (which has no lock around the actual spawn/connect step). Fixed with a pending-install guard (`_tryAcquireInstallLock`) covering the whole flow, released on every exit path (verified this personally at the code level, not just from the report) — network error, refusal, no-consent outcome, stale-context skip, modal cancel, and both outcomes of the final install call. Also added a stale-context check (`btn.isConnected`) so the modal doesn't pop up on top of a screen the user has since navigated away from.
- Cleanup: extracted `_handleInstallOutcome()` to remove three near-identical success/error-handling blocks; extracted `_findCollisionEntry()` as a pure function (matching `_cardActionState`/`_isCodingSoft`'s existing "pure so it's unit-testable without a DOM" pattern) so decision #10's collision check has test coverage where it previously had none; `_errorMessage()` now always returns a string (defensive — no live backend response triggers the gap today, but it directly closes the class of bug this function exists to prevent).

Explicit TODOs for Increment 4b (not built here):
- Secret-collection UI for pending/disabled MCP connections (fill `missing_secrets`, flip `enabled: true`).
- Command discovery (decision #12): expose `COMMAND_REGISTRY`, add a "COMMANDS" section to the existing `/` compose-bar dropdown.
- The test suite for this increment (`tests/marketplace_verified_consent.test.js`) only unit-tests the file's pure helper functions (no DOM/`fetch` available in its `vm`-based harness, and no jsdom in this repo) — it does not and structurally cannot exercise `_installVerifiedPlugin`'s real two-fetch network wiring or `_showVerifiedConsentModal`'s real DOM construction. That coverage exists only as the one-time manual/Playwright verification described above, which won't re-run in CI.

#### Increment 4b (commit `365f0c8`) — secret-collection UI + command discovery

The last increment of this milestone — once this lands, the only remaining step is flipping `marketplace_claude_plugins_official_enabled` to default-on.

- **Secret completion (closes Increment 3's open TODO)**: `mcp.manager.complete_pending_secrets(connection_id, values)` fills in a pending connection's `missing_secrets`, resolving both conventions symmetrically with how Increment 3 detects them ({PLACEHOLDER} template syntax, and the "declared as an empty string" convention), then delegates to the same `add_or_update` live-connect path a manually-added connection uses. New route `POST /api/config/mcp/{id}/complete-secrets` (404 if the connection doesn't exist, 400 if already enabled). Frontend: `window.openMcpCompleteSecretsModal` in `mcp_add_modal.js` reuses the EXISTING `buildPlaceholderFields` UI (decision #5 — same mechanism a hand-added connection's `{placeholder}` fields already use, not a new form), wired to a new "Complete setup" button + plugin-ownership badge ("From the 'X' plugin") in the Connections settings list.
- **Command discovery (decision #12)**: `GET /api/marketplace/commands` exposes `COMMAND_REGISTRY` as `[{name, description, plugin_id}]`; bootstrapped into the page as `window.__PLUGIN_COMMANDS__` the same way `__USER_SKILLS__`/`__MCP_SKILLS__` already are. A new "COMMANDS" section in the existing `/` compose-bar dropdown (`_openSkillPickerDropdown`), filtered via a new pure `_fuzzyFilterCommands` (mirrors `_fuzzyFilterSkills`), selecting a command inserts `/name ` as plain text (not a chip — a command is a parameterized prompt template, not a skill activation). `window.registerPluginCommand` is the live-update hook so a freshly installed plugin's commands appear in the dropdown immediately, called from `marketplace-pane.js`'s `_handleInstallOutcome` using a new `commands` field the install response now carries.

Adversarial review found and fixed before commit (3 parallel finder angles — each also independently verified several hypotheses as NOT bugs, logged below so they aren't re-litigated):
- **Credential leak (the most severe finding of this milestone)**: `complete_pending_secrets` substitutes real secret values into a server's config BEFORE attempting to connect. If that connect attempt then fails, the underlying MCP client's error messages routinely echo back the full config (e.g. a URL with the now-resolved secret embedded as a query param) — and unlike every other secret-bearing field in this codebase, `connect_error` was never masked before being persisted and rendered directly as page text. Fixed: a new `_mask_secrets_in_text` scrubs every submitted secret value out of the error message before it's stored or returned, reusing the existing `_mask_secret` bullet+last-4-chars convention.
- **Blank/incomplete secret submission could silently make things worse, not just fail to help**: nothing checked that a submission actually covered every declared `missing_secrets` name, or that submitted values were non-blank. Combined with `add_or_update`'s own "blank field preserves the existing stored value" merge behavior, a blank submission could re-persist the ORIGINAL unresolved `{PLACEHOLDER}` literal as if it had been resolved — `missing_secrets` cleared, `enabled: true` — with zero trace that nothing was actually fixed. Fixed: validated up front, before any mutation; a missing/blank required value now returns a clear per-name error and leaves the stored connection completely untouched. Mirrored with a frontend guard.
- **Health-check skip regressed an unrelated, already-working case**: the new "don't health-check a pending connection" logic keyed on `enabled === false` generically, but a connection can also be disabled because its connect attempt genuinely FAILED (not because it's missing secrets) — that case used to get an accurate health-check error dot, and after this change silently got neither a health check nor the "Complete setup" button (which is correctly gated on `missing_secrets`), becoming invisible and unrecoverable in the UI. Fixed: narrowed the skip condition to specifically the "has missing_secrets" case.
- **Stale modal instance could destroy an unrelated, actively-open modal**: the modal system uses a shared singleton `close()`; a slow fetch for a modal the user already closed could resolve later and tear down whatever DIFFERENT modal the user has since opened, discarding their in-progress work with no warning. Fixed: the fetch callback now verifies its own modal instance is still the active one before acting.
- **Concurrent-completion race on the same connection id**: the double-submit guard was a per-invocation closure variable, not a lock — closing and reopening the modal for the same still-in-flight connection could fire two concurrent completion requests for the same id. Fixed with a module-level pending-set keyed by connection id, mirroring Increment 4a's `_pendingVerifiedInstalls` pattern.
- Client/server command-name-collision semantics diverged: the client's live-update hook never overwrote a same-named command, while the server's registry does (accepted "last wins" per decision #11a) — so the dropdown could show stale attribution for a command whose actual behavior had already changed server-side. Fixed to match server semantics.
- Cleanup: extracted a shared restamp helper for the "reload → find → stamp plugin_id → clear stale fields → save" pattern that had ALREADY drifted subtly between `complete_pending_secrets` and Increment 3's `register_plugin_mcp_server` — the same class of duplication-drift Increment 3's own review caught once already. Also de-duplicated the dropdown's SKILLS/COMMANDS row-focus-wiring code.
- Ruled out (verified, not bugs): plain-text-node insertion via `_replaceAtHashInInput` (no chip-specific API assumptions); keydown-handler staleness against `PLUGIN_COMMANDS` (re-queries the live DOM, not a cached array); `complete_pending_secrets`'s entry-builder missing fields vs. `register_plugin_mcp_server`'s (confirmed a superset, not a gap); `COMMAND_REGISTRY` startup-ordering (populated synchronously before any request is served); inline `style.cssText` on new UI elements (matches this file's existing, unchanged convention in the same function).

With this increment, the milestone's backend and frontend are both complete.

#### Flag flip (commit `e1155ee`) — `marketplace_claude_plugins_official_enabled` now defaults `True`

The one-line change: `web/marketplace/registry.py`'s `refresh_catalog()` reads `cfg.get("marketplace_claude_plugins_official_enabled", True)` (was `False`) — this is the actual default's home, not `config.py` (which only lists the key in `PATCHABLE_CONFIG_KEYS` so it *can* be overridden; it never set a default value itself, correcting an earlier version of this doc that implied otherwise). An admin/operator can still explicitly set it to `False` to opt out.

This is the milestone's go-live moment: the ~284-entry `claude-plugins-official` catalog (including `amd-skills`, the plugin that started this whole milestone) is now visible by default in every user's Skills and Plugins settings, with the full reviewed path behind it — consent gate, coding-redirect, MCP registration, secret completion, command discovery.

Updated `tests/marketplace/test_claude_plugins_official.py`'s two default-behavior tests to match: `test_refresh_catalog_default_fetches_claude_plugins_official` (was `..._does_not_fetch...`, asserting the now-obsolete old default) and `test_refresh_catalog_explicitly_disabled_does_not_fetch_claude_plugins_official` (the inverse of the old "explicitly enabled" test — the opt-out path still needs coverage now that opt-OUT, not opt-in, is the override case).

---

### Post-milestone fixes (found via live testing after go-live)

Real usage surfaced bugs no amount of code review caught, because they only show up against the actual live catalog/live browser session. Same rigor applied: root-cause investigation before any fix (per systematic-debugging discipline), then the same implement → adversarially review → verify → commit loop as every increment above.

#### Fix — bundled plugin skills never registered into the client-side "/" dropdown

**Symptom (user-reported):** after installing `amd-skills`, typing `/` and searching for one of its 7 bundled skills showed nothing.

**Root cause:** `_handleInstallOutcome` (added in Increment 4a/4b) called `window.registerPluginCommand` for each newly-installed *command*, but never called `window.registerUserSkill` for the newly-installed *skills* — unlike `_install()`'s generic single-skill path, which already does this for its one `skill.id`. Server-side registration (`shared.load_installed_skill_prompts`) always worked correctly, so the model could still use these skills via natural language — but the client-side `SKILL_REGISTRY` powering the `/` dropdown never learned about a plugin bundle's skills without a full page reload.

**Fix:** `_handleInstallOutcome` now calls `window.registerUserSkill` for every id in the install response's `skill_ids`, deriving a readable label via a new pure `_deriveBundledSkillLabel(skillId, pluginId)` (strips the `{plugin_id}__` namespace prefix, title-cases the remainder — e.g. `amd-skills__local-ai-use` → "Local Ai Use"). Covered by `tests/marketplace_bundled_skill_registration.test.js`.

#### Fix — three real-world MCP-manifest-parsing gaps (found via the `datadog` plugin, scope-checked against the wider catalog)

**Symptom (user-reported):** installing `datadog` (a real catalog plugin whose entire purpose is "a preconfigured Datadog MCP server") showed a consent dialog with no mention of any MCP server or required secrets.

**Root-caused via direct investigation of the real `datadog-labs/claude-code-plugin` repo** (not guessed) to three independent gaps in `_discover_plugin_mcp_manifest`/`_discover_plugin_mcp_manifest_from_files`/`_missing_secrets_for_server` (installer.py) and `_find_placeholders` (mcp/normalizer.py):

1. **A plugin's `.claude-plugin/plugin.json` can point at a custom-named MCP config file via a STRING `mcpServers` field**, instead of shipping the canonical `.mcp.json` filename. Confirmed: Datadog's `plugin.json` has `"mcpServers": "./.dd_claude-code_mcp.json"` — discovery only ever globbed for the literal `.mcp.json` name, never read this pointer at all. (Also confirmed present in the `atlassian` plugin — a real, recurring Claude Code convention, not a Datadog-only quirk — though its pointer happens to resolve to the canonical filename, so it wasn't currently broken.)
2. **Secret placeholder detection only matched bare `{VAR}`, not bash-style `${VAR}` / `${VAR:-default}`.** Confirmed: Datadog's real MCP config uses `"${DD_API_KEY:-}"`/`"${DD_MCP_DOMAIN:-not-setup}"` — the `:-default` breaks the old regex's character class, so these secrets were entirely undetected. **This was the safety-critical one**: undetected means the connection would have been live-spawned with the literal unresolved `${DD_API_KEY:-}` string sent as a real HTTP header to Datadog's servers — reopening the exact class of issue the Increment 3/4b consent-gate work was built to prevent.
3. **Some real `.mcp.json` files skip the `"mcpServers"` wrapper key entirely.** Confirmed via a wider catalog sample (found while scope-checking, unrelated to Datadog): `airtable`'s `.mcp.json` is `{"airtable": {"type": "http", "url": "..."}}` — no wrapper key at all. The parser only ever read `config.get("mcpServers")`, so Airtable's MCP server (no secrets even needed) was silently invisible too.

**Fixes:** (1) plugin.json's `mcpServers` string field is now resolved (with a path-traversal guard) to find the pointed-to file, merged in alongside standalone `.mcp.json` discovery, not replacing it — the canonical-filename convention is still the majority case per a live survey of ~18 real MCP-bearing catalog plugins. (2) a second regex (`_BASH_PLACEHOLDER_RE`) matches the bash-parameter-expansion form; `complete_pending_secrets`'s substitution updated to resolve it too. (3) `_mcp_manifest_from_dict` now recognizes the bare (unwrapped) form when every top-level value looks server-shaped (has a `type`/`command`/`url`/`args`/`env` key) — narrow enough that an unrelated JSON file isn't misinterpreted. `get_claude_plugins_official_capabilities`'s `has_mcp` flag changed from a bare filename check to `<filename check> or bool(<real discovery result>)`, since a filename-only check would have silently reproduced the bug even with discovery itself fixed.

Live-verified (real GitHub network calls, not mocked) against the actual catalog after the fix: `datadog` → `has_mcp: true`, `mcp_servers: [{"name": "mcp", "needs_secrets": ["DD_API_KEY", "DD_APPLICATION_KEY", "DD_MCP_DOMAIN", "DD_MCP_TOOLSETS"]}]`; `airtable` → `has_mcp: true`, `needs_secrets: []`.

**Adversarial review found two further real bugs in the fix itself** (both matching invariant-violation patterns this milestone has now hit multiple times):
- **Merge-order regression**: the in-memory discovery function's refactored sort (by directory `/`-count) tied root against any depth-1 bundled skill dir (both 0 slashes) — meaning the skill dir could now *win* a same-name server collision against the plugin root, the opposite of the documented intent and a divergence from the on-disk sibling function. Fixed by explicitly appending root last, unconditionally, matching the on-disk function's list-concatenation approach exactly.
- **On-disk vs. in-memory path-traversal scope divergence**: a bundled skill dir's `plugin.json` pointer was confined to that skill dir's own subtree on-disk, but could escape into sibling directories in the in-memory (consent-preview) resolver — the same "preview shows something different from what installs" class of bug already fixed twice earlier in this milestone (the `pinned_ref` TOCTOU, the `.mcp.json`-scope mismatch). Fixed by aligning the in-memory resolver's base-dir semantics to the on-disk one.
- **Also found and fixed**: `_substitute_placeholder`'s secret substitution was a pre-existing (not newly introduced) bug — sequential multi-pass replacement across multiple collected secrets could corrupt an already-substituted value if it happened to contain brace-shaped text (e.g. `{OTHER_VAR}`) — but this fix's whole purpose is making *more* secrets successfully match and flow through that exact function, so it mechanically increases real-world exposure. Fixed with a single-pass combined regex (`_COMBINED_PLACEHOLDER_RE`), the same pattern already used for the `$ARGUMENTS`/positional-arg re-scan bug fixed earlier in Increment 2 — verified directly (not just via the report) to be order-independent and fully backward-compatible.

#### Fix — plugin skills are written for the Claude Code CLI, not Gator (found via `datadog: any active incidents?`)

**Symptom (user-reported):** asking Gator "datadog: any active incidents?" activated datadog's bundled `ddsetup`/`ddconfig`/`ddtoolsets` skills, and the agent — following those skills' own onboarding script verbatim — told the user to run slash commands (`/ddsetup`, `/reload-plugins`, `/mcp`), tried to "read the skill guide" for a skill literally named `datadog` (→ "No SKILL.md found for skill 'datadog'"), tried a bare string as a URL (→ "URL must start with http://"), and ran a shell command that timed out. All dead ends.

**Root cause:** these plugin skills' `SKILL.md` files are authored for the **Claude Code CLI**. Their setup procedure assumes Claude-Code-only mechanics: slash commands, a `${CLAUDE_PLUGIN_DATA}` directory, and generic read/edit access to an on-disk MCP "registration file" (`.dd_claude-code_mcp.json`) it computes the path to itself. None of that exists in Gator — MCP setup happens in **Settings → Connections** via the Increment 4b "Complete setup" flow, which *already* correctly reported the datadog connection needs `DD_API_KEY`/`DD_APPLICATION_KEY`/`DD_MCP_DOMAIN`/`DD_MCP_TOOLSETS`. The connection was configurable the whole time; the agent just had no way to know that and instead ran the CLI script into a wall. This is **cross-cutting**: any plugin whose skills embed CLI-specific onboarding hits the same wall.

**Fix (two parts, agreed scope — Options 1 + 2 of four considered; deep-link-to-modal and activation-gating were deferred):**
1. **Context preamble (`web/routes/chat.py`)** — when a plugin-bundled skill's `SKILL.md` is injected, prefix it once with `_GATOR_PLUGIN_SKILL_PREAMBLE`: "you're in AI Gator, not Claude Code — no slash commands, MCP setup is in Settings → Connections via Complete setup, don't read/edit plugin registration files or `${CLAUDE_PLUGIN_DATA}`, and call `mcp_connection_status` to check state." Detection via `_is_plugin_bundled_skill()`: primary signal is membership in an installed-plugin's `skill_ids` list from `installed-skills.json` (`load_installed()`), which also catches single-SKILL.md plugins registered under a bare plugin_id; falls back to the `{plugin_id}__{relpath}` `__`-in-id heuristic.
2. **`mcp_connection_status` agent tool (`web/skills/_always_on/tools.py`, always-on)** — lets the agent check a connection's real state (enabled / `missing_secrets` / `needs_setup` / status) so it can say precisely "Datadog needs setup — open Settings → Connections → Complete setup" instead of guessing from tool availability. Built entirely on `mcp.manager.list_with_status()` (the already-masked, UI-safe view) and re-emits only a 9-field whitelist — structurally incapable of surfacing `auth_value`/`env`/`extra_headers`.

**Adversarial review found and fixed three real gaps in the fix:**
- **Preamble injected at only 2 of 4 skill-injection sites** (double-confirmed by two independent reviewers): the mid-stream auto-activate path (`chat.py`, model names a skill mid-turn) and the background/scheduled-task worker (`app.py`) both injected plugin `SKILL.md` bodies with no preamble — silently defeating the fix on those paths. Refactored all four sites to route through one shared `_append_skill_prompt(system, sid, preamble_done)` helper so the preamble can't go missing from any path; the mid-stream site seeds its flag from whether `_current_system` already carries the preamble, to avoid double-injection.
- **`connect_error` piped to the model unmasked** — the tool surfaced `connect_error` verbatim; while `complete_pending_secrets` masks it, the plugin-registration failure path stores it raw, and an MCP client error can echo a server URL with an embedded credential. Since this tool is the first thing to route that field into the *model's context* (the Settings UI only shows it to the user), added `_sanitize_connect_error` (strips URL userinfo + sensitive query-param values, truncates) consistent with the milestone's "never surface a credential-bearing field unmasked" posture.
- **Option 1 had zero test coverage** (the user-facing half) — added `tests/test_plugin_skill_preamble.py` proving the `_append_skill_prompt` invariant (plugin body ⟹ preamble present exactly once; native-only ⟹ absent; ordering; no re-injection), plus connect_error-sanitizer + no-leak tests. Also fixed a misleading "Ready" status for an enabled-but-zero-tools connection ("Enabled (no tools discovered yet)") and replaced a silent `except: pass` in the registry lookup with a debug log.

**Known follow-up (not fixed this round, deliberately out of scope):** `read_skill('datadog')` still returns a confusing "No SKILL.md found… Available skills: [native ids]" if the agent calls it before the plugin skill is classified — the preamble + status tool mitigate but don't fully close that path. Deferred with the deep-link-to-modal (Option 3) and activation-gating (Option 4) ideas.

---

## `plugin.json` Manifest Format

Standard Anthropic fields plus an optional `gator:` block for Gator-specific policy. Claude Code ignores the `gator:` block; Gator reads it. `SKILL.md` YAML frontmatter remains a fallback when `plugin.json` is absent.

```json
{
  "name": "rocm-toolkit",
  "version": "1.2.0",
  "description": "GPU diagnostics and memory management",
  "author": { "name": "AI Gator Team" },
  "license": "MIT",

  "gator": {
    "tier": "verified",
    "gateway_required": true,
    "requires_approval": false
  }
}
```

**Tier values:** `native` · `verified` · `community` · `mine`

---

## Tool Authoring Note

All skill `tools.py` files use Anthropic's tool definition format (`input_schema`). Gator automatically translates this to the correct format for other LLMs (OpenAI, Groq, Ollama) at runtime via `provider.normalize_tool_schema()`. Skill authors do not need to handle this.

```python
TOOL_DEFS = [
    {
        "name": "get_gpu_memory",
        "description": "Get current GPU memory usage for all devices",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "integer", "description": "GPU device index"}
            },
            "required": []
        }
    }
]
```

---

## Historical design notes (pre-2026-08-07 — superseded where in conflict)

The earlier design (below) proposed a broader P0/v1/P1 plan including Gator-native agents/hooks, `bin/` PATH injection, a `~/.config/teamspoc/` → `~/.gator/` migration, and dual-marketplace (`claude-plugins-official` + `claude-plugins-community`) support. The 2026-08-07 milestone **narrows** this to A+B+E with the rationale above. Notable supersessions:

- **Agents/hooks/`bin/`** — deferred (see Deferred table), not P0.
- **`claude-plugins-community`** — not used; only `claude-plugins-official` is the source. (It is not present in the local `known_marketplaces.json`.)
- **Slash commands** — reduced to the *minimal* runtime in decision #11 (the earlier doc assumed a richer command surface).
- **Config-folder migration** — a separate concern, not part of this milestone; the milestone uses whatever base `web/config.py` resolves (`PLUGINS_DIR`, `INSTALLED_SKILLS_DIR`).
- **Marketplace = discovery/ease, not new capability** — the earlier doc framed the marketplace as the extension mechanism; this milestone is explicit that Gator already *has* MCP + skills, and the marketplace's value is discovery + one-click + guided secrets for a mixed/non-developer audience, with coding ceded to OpenCode.

The prior directory-structure sketch (`~/.gator/plugins/cache/{marketplace}/{plugin}/{version}/` with `plugin.json`, `SKILL.md`, `tools.py`, `bin/`, `agents/`, `hooks/`, `.mcp.json`) remains the **structural reference** for a full plugin folder; this milestone only *loads* the `plugin.json` / `skills/**/SKILL.md` / `tools.py` / MCP-server pieces of it, and defers `bin/` / `agents/` / `hooks/`.
