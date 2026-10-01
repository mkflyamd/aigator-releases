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
| `H_OTA_updater_supply_chain_compromise_due__02` | OTA updater supply chain compromise (no integrity check before install) | **Implemented** | [design](../superpowers/specs/2026-09-30-ota-updater-integrity-design.md) / [plan](../superpowers/plans/2026-09-30-ota-updater-integrity.md) | First in remediation order. Manifest URL/version pinning, checksum verification, and Authenticode signature + pinned-thumbprint verification now gate every OTA install; all fail closed. Final whole-branch review clean (one Important downgrade-prevention gap found and fixed post-review). |
| `H_Code_runner_skill_used_for_lateral_movem_06` | Code-runner skill usable for lateral movement / unrestricted network & filesystem egress | Not started | — | Second in remediation order. |
| `H_Local_OAuth_token_theft_from_filesystem_01` | OAuth tokens stored in plaintext JSON on local filesystem | Not started | — | Third in remediation order. |
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
