# Threat Model Remediation Tracker

**Source report:** AMD AI Threat Modeling Self-Service Tool — run ID `gator-tm-001` (`SystemReport.pdf`)
**Scope:** AI Gator desktop app (Electron shell → FastAPI web app → agent loop → skills/MCP)
**Severity summary:** 0 Critical / 6 High / 7 Medium / 0 Low

This doc tracks remediation status for each finding so we have one place to check progress and
link out to the detailed design spec for each fix. Findings are being tackled **least effort/risk
first**, per team decision.

## High findings

| ID | Title | Status | Spec | Notes |
|----|-------|--------|------|-------|
| `H_OTA_updater_supply_chain_compromise_due__02` | OTA updater supply chain compromise (no integrity check before install) | **Implemented** | [design](../superpowers/specs/2026-09-30-ota-updater-integrity-design.md) / [plan](../superpowers/plans/2026-09-30-ota-updater-integrity.md) | First in remediation order. Manifest URL/version pinning, checksum verification, and Authenticode signature + pinned-thumbprint verification now gate every OTA install; all fail closed. Final whole-branch review clean (one Important downgrade-prevention gap found and fixed post-review). Real-binary testing then found the self-signed cert reports `UnknownError`, not `Valid`, on end-user machines; the signature check now accepts that status only with the pinned thumbprint (tampered files still report `HashMismatch`). Known limitation: until a CA-issued cert is adopted, the pinned thumbprint is the sole signature trust anchor. |
| `H_Code_runner_skill_used_for_lateral_movem_06` | Code-runner skill usable for lateral movement / unrestricted network & filesystem egress | **Deferred** | — | Deferred by team decision; revisit after the OAuth finding. Decisions so far: build a thin Windows AppContainer launcher (no admin, no new dependency) behind a small `launch_sandboxed(...)` interface; no off-the-shelf library fits (Codex's Windows sandbox needs elevation, MXC is early preview and not yet a security boundary, microsandbox is VM-based). Trimmed plan (one step per acceptance criterion, no proxy): (1) AppContainer process with run-folder-only access and no network; (2) run declares extra paths, user approves each path, access granted for that run only; (3) run declares host:port, user approves, network on for that run only (partial vs. the report: destination is shown but not enforced per-destination; add a proxy only if reviewers require it); (4) one admin-writable machine-wide policy file (disable / no-network / strict-filesystem) read at startup; (5) metadata-only approval/denial lines in turn telemetry. Also strip secrets (`GITHUB_TOKEN`, `JIRA_*`, etc.) from the sandboxed process environment. Known gap: `shell_runner` is also always-on and unsandboxed, so it bypasses this; not named in the report. The same launcher is intended for reuse by `H_Malicious_marketplace_or_MCP_skill_execu_03`, which is larger (marketplace `tools.py` is hot-loaded in-process today). Not yet verified by a spike. |
| `H_Local_OAuth_token_theft_from_filesystem_01` | OAuth tokens stored in plaintext JSON on local filesystem | **Implemented** | [design](../superpowers/specs/2026-10-05-oauth-token-storage-design.md) | Tokens and config PATs are now DPAPI-encrypted under `~/.gator/secrets/`; legacy plaintext is migrated on read and at startup (existing plaintext was migrated and shredded); backups are scrubbed; `POST /api/auth/clear` plus a Settings button; rotation covered by tests. Known limitations: DPAPI does not stop same-user malware; Microsoft tokens are cleared locally only (no server-side revocation); LLM API keys, `google_oauth_client_secret`, MCP `auth_value`/spawn env, and the env-var copy of PATs are second-pass; an unreadable blob (profile or password reset) requires re-authentication. |
| `H_Malicious_marketplace_or_MCP_skill_execu_03` | Malicious marketplace/MCP skill execution | Not scheduled | — | Trust tiers (`shared.TOOL_TIER_MAP`) are advisory only today; needs its own design. |
| `H_Prompt_injection_leading_to_unintended_d_04` | Prompt injection leading to unintended destructive actions | Not scheduled | — | Partially mitigated today by HITL gating on send/create/delete; needs gap analysis. |
| `H_Reliance_on_user_endpoint_security_for_p_10` | Reliance on user endpoint security as the sole protection boundary | Out of code scope | — | Primarily an IT/policy control (endpoint baseline enforcement), not a code fix. Flagged to stakeholders, not tracked as an implementation item here. |

## Medium findings

| ID | Title | Status |
|----|-------|--------|
| `M_Localhost_CSRF_token_exposure_via_browse_05` | Localhost CSRF token exposure via browser | Not scheduled |
| `M_Inadequate_separation_between_skill_trus_07` | Inadequate separation between skill trust tiers | Not scheduled |
| `M_Potential_leakage_of_sensitive_metadata__08` | Potential leakage of sensitive metadata | Not scheduled |
| `M_Misconfiguration_of_marketplace_allowed__09` | Misconfiguration of marketplace allow-list | Not scheduled |
| `M_Lack_of_strong_integrity_assurance_for_s_11` | Lack of strong integrity assurance for skills | Not scheduled |
| `M_Potential_misuse_of_delegated_SaaS_permi_12` | Potential misuse of delegated SaaS permissions | Not scheduled |
| `M_Future_regression_risk_in_CSRF_HITL_enfo_13` | Future regression risk in CSRF/HITL enforcement | Not scheduled |

Medium findings are deferred until the six High findings above are addressed (or explicitly
descoped, as with #10).

## Process

Each High finding gets its own brainstorming → spec → implementation-plan → implementation cycle:

1. Design spec written to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`, aligned to the
   report's exact remediation steps and acceptance criteria for that finding.
2. Spec approved by the team.
3. Implementation plan produced (`writing-plans` skill).
4. Implementation + tests land on `security/threatmodel-remediation`.
5. This table is updated with status + links.

## Branch

All remediation work for this effort happens on `security/threatmodel-remediation` (branched off
`main`).
