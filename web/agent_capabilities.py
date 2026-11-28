"""Which terminal agents can be woken and messaged through the relay, and how they differ.

An agent is in CAPABILITIES when its stored session can be resumed, it reports its own
state (see agent_state) and it can be given the message tool (see agent_mcp). A new agent
is one more entry here plus its launch config and ready hook.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    # The session id is not chosen at launch; a hook records it beside the state file.
    session_from_hook: bool = False
    # The hooks only exist in newer builds of the agent.
    hooks_need_version_check: bool = False
    # A running terminal is only a target when it was launched with the message tool.
    live_needs_token: bool = False


CAPABILITIES = {
    "claude": Capability(),
    "crush": Capability(session_from_hook=True, hooks_need_version_check=True, live_needs_token=True),
    "opencode-bare": Capability(session_from_hook=True, hooks_need_version_check=True, live_needs_token=True),
}


def relayable(agent: str | None) -> bool:
    """True when this agent can be woken, messaged and given the message tool on this machine."""
    cap = CAPABILITIES.get(agent or "")
    if cap is None:
        return False
    if not cap.hooks_need_version_check:
        return True
    import agent_state
    import generic_agent

    return agent_state.hooks_supported(agent, generic_agent.find_agent_binary(agent))


def live_target_ok(agent: str | None, pty_id: str) -> bool:
    """A running terminal Gator is willing to wake or message: nothing is assumed about one that cannot be confirmed."""
    if not relayable(agent):
        return False
    if not CAPABILITIES[agent].live_needs_token:
        return True
    import agent_mcp

    return agent_mcp.holds_token(pty_id)


def session_from_hook(agent: str | None) -> bool:
    cap = CAPABILITIES.get(agent or "")
    return bool(cap and cap.session_from_hook)
