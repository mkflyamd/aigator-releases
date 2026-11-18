"""Share a Mine skill through OneDrive and install one that was shared with you."""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from marketplace import installer, skill_audit
from marketplace.loader import load_skill_tools
from routes.marketplace import (
    _enforce_tier,
    _install_failure,
    _note_tools_error,
    _record_grants,
    _require_digest,
)
from security import verify_csrf
from shared import load_installed_skill_prompts
from skills._sharing import destinations, drafts, messages, publisher, receiver
from skills._sharing.errors import ShareError
from skills._sharing.provider import GraphSharingProvider

router = APIRouter()
logger = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")

# 403 is not used here: the app already answers 403 for a bad CSRF token and for policy blocks.
_STATUS = {
    "not_found": 404,
    "invalid": 400,
    "invalid_link": 400,
    "too_large": 400,
    "not_mine": 400,
    "conflict": 409,
    "not_yours": 409,
    "collision": 409,
    "content_changed": 409,
    "tampered": 409,
    "throttled": 429,
    "locked": 423,
    "forbidden": 422,
    "audience_unacknowledged": 422,
    "policy_blocked": 422,
}


class FolderRef(BaseModel):
    drive_id: str = Field(min_length=1, max_length=512)
    folder_id: str = Field(min_length=1, max_length=512)
    web_url: str = Field(default="", max_length=2048)
    name: str = Field(default="", max_length=256)


def _check_emails(people: list[str]) -> list[str]:
    for person in people:
        if not _EMAIL.match(person):
            raise ValueError(f"not an email address: {person!r}")
    return people


class PublishRequest(BaseModel):
    skill_id: str = Field(min_length=1, max_length=128)
    people: list[str] = Field(default_factory=list, max_length=50)
    root: FolderRef | None = None
    audience_ack: bool = False

    @field_validator("people")
    @classmethod
    def _emails(cls, people: list[str]) -> list[str]:
        return _check_emails(people)


class Person(BaseModel):
    name: str = Field(default="", max_length=200)
    email: str = Field(max_length=320)

    @field_validator("email")
    @classmethod
    def _email(cls, email: str) -> str:
        _check_emails([email])
        return email


class DraftRequest(BaseModel):
    skill_id: str = Field(min_length=1, max_length=128)
    channel: str = Field(pattern="^email$")
    people: list[Person] = Field(min_length=1, max_length=50)
    message: str = Field(min_length=1, max_length=4000)
    message_html: str = Field(default="", max_length=8000)


class ReviewRequest(BaseModel):
    link: str = Field(max_length=2048)
    version: int | None = Field(default=None, ge=1)


class InstallRequest(BaseModel):
    link: str = Field(max_length=2048)
    version: int = Field(ge=1)
    digest: str = ""


def _provider() -> GraphSharingProvider:
    from skills._m365.helpers import GraphClient

    return GraphSharingProvider(GraphClient())


def _author_name() -> str:
    from skills._m365.helpers import GraphClient

    me = GraphClient().get("/me", params={"$select": "displayName,userPrincipalName"})
    return me.get("displayName") or me.get("userPrincipalName") or ""


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ShareError as err:
        raise HTTPException(
            status_code=_STATUS.get(err.code, 502), detail={"error": err.code, "message": err.message}
        ) from err
    except Exception as exc:
        logger.warning("skill sharing request failed: %s", exc)
        raise HTTPException(
            status_code=502, detail={"error": "unknown", "message": "Could not complete that with OneDrive."}
        ) from exc


@router.get("/api/skills/share/locations")
def share_locations(skill_id: str = Query(min_length=1, max_length=128)):
    return _call(destinations.locations, _call(_provider), skill_id)


@router.get("/api/skills/share/check")
def check_share_location(
    skill_id: str = Query(min_length=1, max_length=128),
    drive_id: str = Query(default="", max_length=512),
    folder_id: str = Query(default="", max_length=512),
):
    if bool(drive_id) != bool(folder_id):
        raise HTTPException(
            status_code=400, detail={"error": "invalid", "message": "Give both drive_id and folder_id, or neither."}
        )
    return _call(destinations.check, _call(_provider), skill_id, drive_id, folder_id, _call(_author_name))


@router.post("/api/skills/share/publish", dependencies=[Depends(verify_csrf)])
def publish_skill(req: PublishRequest):
    provider = _call(_provider)
    author = _call(_author_name)
    root = req.root.model_dump() if req.root else None
    return _call(
        publisher.publish,
        provider,
        req.skill_id,
        author=author,
        root=root,
        people=req.people,
        audience_ack=req.audience_ack,
    )


@router.post("/api/skills/share/draft", dependencies=[Depends(verify_csrf)])
def draft_share_message(req: DraftRequest):
    people = [p.model_dump() for p in req.people]
    return _call(
        drafts.build, skill_id=req.skill_id, people=people, message=req.message, message_html=req.message_html
    )


@router.post("/api/skills/share/review", dependencies=[Depends(verify_csrf)])
def review_shared_skill(req: ReviewRequest):
    ref = _call(messages.parse_share_link, req.link)
    provider = _call(_provider)
    return _call(receiver.review, provider, ref, req.version)


@router.post("/api/skills/share/install", dependencies=[Depends(verify_csrf)])
def install_shared_skill(req: InstallRequest):
    _enforce_tier("shared-skill", "Community")
    _require_digest(req.digest)
    ref = _call(messages.parse_share_link, req.link)
    provider = _call(_provider)
    result = _call(receiver.install, provider, ref, version=req.version, digest=req.digest)
    if not result.get("ok"):
        raise _install_failure(result)
    skill_id = result["skill_id"]
    _record_grants(result, skill_id)
    skill_audit.log_install(skill_id, "Community", "share", req.digest)
    load_installed_skill_prompts()
    _note_tools_error(result, load_skill_tools(skill_id, installer.INSTALLED_SKILLS_DIR / skill_id, "Community"))
    return result
