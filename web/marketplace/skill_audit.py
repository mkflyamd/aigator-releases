"""Outbound-destination logging for marketplace skills (logging only, never blocks)."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("aigator.skill_audit")

MARKER = "AIGATOR-SKILL-OUTBOUND "
MAX_DEST = 50
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _clean(value, limit: int = 200) -> str:
    return _CONTROL.sub("?", str(value))[:limit]


def log_launch(skill_id: str, kind: str, network: bool, declared) -> None:
    hosts = ",".join(_clean(h) for h in declared) or "-"
    logger.info("skill-launch skill=%s kind=%s network=%s declared_hosts=%s",
                _clean(skill_id), _clean(kind, 20), "true" if network else "false", hosts)


def log_outbound(skill_id: str, destinations) -> None:
    for dest in destinations:
        logger.info("skill-outbound skill=%s dest=%s", _clean(skill_id), _clean(dest))


def extract_outbound(stderr: str) -> tuple[list[str], str]:
    """Split the runner's marker lines out of stderr. A skill can forge marker lines; this is a log, not a control."""
    dests: list[str] = []
    kept: list[str] = []
    for line in (stderr or "").splitlines(keepends=True):
        if line.startswith(MARKER):
            dest = line[len(MARKER):].strip()
            if dest and dest not in dests and len(dests) < MAX_DEST:
                dests.append(dest)
        else:
            kept.append(line)
    return dests, "".join(kept)
