"""Fail-closed target resolution and verification for Jira mutations.

The built-in Jira client historically reads one process-global configuration.
That is safe only when exactly one Jira site is connected.  This module is the
boundary for any new state-changing Jira operation: a mutation must carry the
resolved target that was used while drafting it, and success is reported only
after a read from that same target confirms the requested state.

MCP-backed Jira sites are deliberately not silently mapped to the built-in
credentials.  An MCP resource needs an explicit adapter before it is allowed
to mutate anything; this prevents a request for amd.atlassian.net from being
sent to a configured amd-hub.atlassian.net account.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from . import api


class JiraTargetResolutionError(ValueError):
    """Raised when a Jira target is ambiguous, unconfigured, or unsafe."""


def _canonical_base_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise JiraTargetResolutionError("Jira target must be an https URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise JiraTargetResolutionError("Jira target URL must not include credentials, a query, or a fragment.")
    return f"https://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


@dataclass(frozen=True)
class JiraTarget:
    """Immutable Jira site identity captured at draft time.

    ``adapter`` is intentionally explicit.  No code may substitute the
    process-global Jira credentials for an MCP target just because both are
    Atlassian Cloud sites.
    """

    id: str
    base_url: str
    adapter: str
    is_cloud: bool
    connection_id: str = ""
    resource_id: str = ""

    def issue_url(self, issue_key: str) -> str:
        return f"{self.base_url}/browse/{issue_key}"

    def to_dict(self) -> dict:
        return asdict(self)


def configured_builtin_target() -> JiraTarget:
    """Return the sole built-in target, normalized from trusted config.

    This is not a fallback resolver.  It only represents the legacy direct
    Jira configuration and must exactly match a supplied Jira URL.
    """

    base_url = _canonical_base_url(api.jira_browse_url())
    return JiraTarget(
        id=f"builtin:{base_url}",
        base_url=base_url,
        adapter="builtin-rest",
        is_cloud=api.jira_is_cloud(),
    )


def resolve_builtin_target(issue_or_url: str = "") -> JiraTarget:
    """Resolve an issue reference against the configured direct Jira site.

    A full URL is accepted only if it names the configured site.  A key alone
    is inherently site-ambiguous once multiple sites are connected, so callers
    must pass an already-selected target for key-only operations in that case.
    Current direct tools have one selected built-in target, so the key remains
    compatible while URL mismatches fail closed.
    """

    target = configured_builtin_target()
    value = (issue_or_url or "").strip()
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        configured = urlparse(target.base_url)
        same_origin = (
            parsed.scheme.lower() == configured.scheme.lower()
            and parsed.netloc.lower() == configured.netloc.lower()
        )
        configured_path = configured.path.rstrip("/")
        path_matches = not configured_path or (
            parsed.path == configured_path
            or parsed.path.startswith(f"{configured_path}/")
        )
        if not same_origin or not path_matches:
            raise JiraTargetResolutionError(
                f"This Jira URL does not belong to the selected Jira connection "
                f"{target.base_url}. Reconnect or explicitly select the matching Jira site; "
                "AI Gator will not redirect the mutation."
            )
    return target


def target_from_draft(raw: dict) -> JiraTarget:
    """Rehydrate and validate the target captured in a pending HITL draft."""

    if not isinstance(raw, dict):
        raise JiraTargetResolutionError("Jira draft has no resolved target. Re-draft the action.")
    try:
        target = JiraTarget(**raw)
    except TypeError as exc:
        raise JiraTargetResolutionError("Jira draft target is malformed. Re-draft the action.") from exc
    canonical = _canonical_base_url(target.base_url)
    if canonical != target.base_url or target.adapter != "builtin-rest":
        raise JiraTargetResolutionError(
            "Jira draft target is not a supported verified-mutation adapter. Re-draft after selecting a connected Jira site."
        )
    current = configured_builtin_target()
    if target != current:
        raise JiraTargetResolutionError(
            "The Jira connection changed after this draft was prepared. Re-draft so the action can be reviewed against the current site."
        )
    return target


def verified_result(target: JiraTarget, requested: dict, applied: dict, verified: dict) -> dict:
    """Standard success payload. Call only after a target-scoped re-read."""

    return {
        "ok": True,
        "target": target.to_dict(),
        "requested": requested,
        "applied": applied,
        "verified": verified,
    }


def compare_jira_fields(requested: dict, actual: dict) -> tuple[dict, dict]:
    """Return exact, evidence-backed field matches and mismatches.

    Jira expands entity objects returned from GET (for example, a component
    gets a description in addition to the requested ``id``).  A requested
    mapping is therefore compared as a recursive subset of the read-back
    value. Scalars remain exact and a requested list must be represented by
    matching values on the server. This deliberately returns a mismatch when
    a value cannot be established; callers must not infer success from a 2xx.
    """

    def _matches(expected, observed) -> bool:
        if isinstance(expected, dict):
            return isinstance(observed, dict) and all(
                key in observed and _matches(value, observed[key])
                for key, value in expected.items()
            )
        if isinstance(expected, list):
            if not isinstance(observed, list) or len(expected) != len(observed):
                return False
            unmatched = list(observed)
            for value in expected:
                for index, candidate in enumerate(unmatched):
                    if _matches(value, candidate):
                        unmatched.pop(index)
                        break
                else:
                    return False
            return True
        return expected == observed

    confirmed: dict = {}
    rejected: dict = {}
    for field, expected in requested.items():
        observed = actual.get(field)
        if _matches(expected, observed):
            confirmed[field] = observed
        else:
            rejected[field] = {"requested": expected, "actual": observed}
    return confirmed, rejected
