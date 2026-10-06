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
| `H_Code_runner_skill_used_for_lateral_movem_06` | Code-runner skill usable for lateral movement / unrestricted network & filesystem egress | **Implemented (Windows verified on the dev machine; macOS/Linux pending real-system smoke test)** | [design](../superpowers/specs/2026-10-05-code-runner-sandbox-design.md) / [plan](../superpowers/plans/2026-10-05-code-runner-sandbox.md) | `run_python` now runs model code in an OS sandbox behind one `web/sandbox` interface: Windows AppContainer (ctypes, no admin, Job Object tree kill), macOS Seatbelt, Linux bubblewrap. By default the code reads and writes only its run folder, reads the runtime, has no network, and gets an allow-list environment (every token dropped). Extra paths and network need a real user approval: a chat card whose Approve/Deny call CSRF-guarded routes the agent loop cannot reach; the approval must match the same tab and exactly the same normalized set, is used by one run and expires after 10 minutes. Drive roots, the home folder and its parents, `~/.gator` (except `outputs`), `~/.ssh`, `~/.aws`, `~/.azure`, `~/.kube`, `~/.gnupg`, `~/.config/gcloud` (and their parents) can never be granted. A machine-wide admin policy file can disable code, refuse network, refuse extra paths and forbid the user opt-out; a bad policy file fails closed. When the sandbox is unavailable code is blocked (Settings explains the fix) unless the user opts out and the policy allows it. Metadata-only telemetry per run (level, network, extra counts, approval decision). The frozen sidecar is now onedir: the reported `--run-python` "hang" was ~42 s of onefile re-extraction per run (about 1.2 s after the change; no further `backend_entry.py` change was needed). Partial vs. the report: network approval is all or nothing per run (host:port shown, not enforced, no proxy); on Windows approved network uses only the `internetClient` capability, so private/intranet hosts stay unreachable. Known gaps: `run_shell` (shell_runner) is unsandboxed and can run `python` (bypass, not named in the report, unchanged); `packages=[...]` pip installs run unsandboxed in the server process (in enforced mode requirement strings are validated and passed with `--no-input --`); same-user malware and OS sandbox escapes are out of scope. Deviation from the design: on Windows the runtime directories keep a persistent read+execute ACE for the AI Gator container SID (the design said grants are removed after the run; re-granting ~30k files per run was too slow); the run folder and approved extra paths are granted per run and revoked afterwards, a ledger plus startup sweep removes leftovers after a crash, and sandboxed runs are serialized. No steady-state sandboxed run time is recorded (the Task 4 real-run overhead test output was not captured). Approval decisions reach turn telemetry only when a later `run_python` call observes them (the decision itself is in the server log). Verification status: bubblewrap was run for real in WSL Ubuntu only (bubblewrap 0.11.1); the macOS Seatbelt profile has never been run on a real Mac (profile-builder tests only); the Windows AppContainer launcher was verified on the dev machine, while Windows 10, antivirus/EDR reactions, long paths and loopback exemptions are untested; AppImage FUSE mounts under bubblewrap are untested; the macOS profile allows file metadata reads everywhere. A manual smoke test on a real Mac and a real Linux desktop is a release gate (see `docs/BUILD_INSTRUCTIONS.md`, "Code sandbox smoke test (release gate)") and has not yet been run. |
| `H_Local_OAuth_token_theft_from_filesystem_01` | OAuth tokens stored in plaintext JSON on local filesystem | **Implemented (Windows verified; macOS/Linux pending real-vault smoke test)** | [design](../superpowers/specs/2026-10-05-oauth-token-storage-design.md) / [plan](../superpowers/plans/2026-10-05-oauth-token-storage.md); macOS/Linux: [design](../superpowers/specs/2026-10-05-secure-store-macos-linux-design.md) / [plan](../superpowers/plans/2026-10-05-secure-store-macos-linux.md) | Tokens and config PATs are now DPAPI-encrypted blobs under `~/.gator/secrets/` (per-user encryption, not Credential Manager, whose ~2.5 KB limit is too small for Graph tokens); legacy plaintext is migrated on read and at startup (existing plaintext was migrated and shredded); PAT keys are scrubbed from every `config.json.*` copy and `*.damaged` file; `POST /api/auth/clear` plus a Settings button; rotation covered by tests; a guard test blocks reintroducing plaintext token files. Verified read-only against the developer's real profile. Known limitations: macOS and Linux use a vault-held AES-GCM key (Keychain / Secret Service via `keyring`), implemented but not yet smoke-tested on a real Mac or Linux desktop; the macOS/Linux backends were verified only with a fake vault on Windows and need a manual smoke test on a real Mac and a Linux desktop before release; Linux without a keyring uses a user-only key file (reduced protection, shown in Settings); macOS fails closed if the Keychain is unavailable; DPAPI does not stop same-user malware; Microsoft tokens are cleared locally only (no server-side revocation); LLM API keys, `google_oauth_client_secret`, MCP `auth_value`/spawn env, and the env-var copy of PATs are second-pass; an unreadable blob (profile or password reset) requires re-authentication; copies of `config.json` kept elsewhere are not discovered. Packaged installer not yet rebuilt; to be built after review and merge. |
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
