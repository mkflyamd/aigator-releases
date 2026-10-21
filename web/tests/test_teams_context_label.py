"""_teamsContextLabel must classify group vs 1:1 Teams chats correctly.

Bug (2026-09-30 incident, round 1): the original version treated "has a
chat_topic" as proof of being a group chat. Wrong — a 1:1 chat, including
an unmaterialized "19:preview-..." stub, also has a topic (the other
person's display name). Group vs 1:1 is now determined from the chat_id's
own real shape instead.

Bug (2026-09-30 incident, round 2): the fix for round 1 then used
`names.includes(',')` as a recipient-COUNT heuristic on the "no chat_id
yet" fallback path — also wrong, because this org's directory formats a
SINGLE person's name as "Last, First" (e.g. "Valliyappan, Ram",
"Kulkarni, Mayuresh"), so almost every single-recipient draft's name
already contains a comma. That mislabeled ordinary 1:1 drafts as "Group
message to ...".

Both rounds shipped with only source-string presence tests (checking a
substring like `chatId.startsWith('19:preview-')` exists) — which passed
both times while the actual DECISION LOGIC was still wrong for a real
input shape. This file switches to real behavioral testing instead:
extracting the live function from app.js and executing it via Node with
concrete inputs, asserting the exact returned label — the only way to
actually catch "the right substring is present, but the branch it's in
still produces the wrong answer for this input."
"""
import json
import pathlib
import subprocess
import sys

import pytest

APP_JS_PATH = pathlib.Path(__file__).parent.parent / "static" / "app.js"
APP_JS = APP_JS_PATH.read_text(encoding="utf-8")

_START = APP_JS.index("function _teamsContextLabel(data)")
_END = APP_JS.index("\n}\n", _START) + 3
_FN_SRC = APP_JS[_START:_END]


def _call(data: dict) -> str:
    """Execute the real, current _teamsContextLabel from app.js via Node
    with the given `data` object and return its output."""
    script = _FN_SRC + f"\nconsole.log(_teamsContextLabel({json.dumps(data)}));"
    result = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"node failed: {result.stderr}"
    return result.stdout.strip()


@pytest.fixture(scope="module", autouse=True)
def _require_node():
    if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
        pytest.skip("node not available")


class TestPreviewStubIsDirectMessage:
    """The exact original incident: a not-yet-materialized preview chat_id
    with a chat_topic set must be a 1:1 DM, never a Group."""

    def test_preview_id_with_topic_and_no_names(self):
        label = _call({
            "chat_id": "19:preview-ab0dc05a-05dd-4c99-a9af-c33a85ce1997",
            "chat_topic": "ValliyappanRam,AI Agent",
            "to": "",
            "to_names": "",
        })
        assert label.startswith("Direct message")
        assert "Group" not in label


class TestLastCommaFirstNameIsNotMistakenForMultipleRecipients:
    """The round-2 incident: this org's directory formats a single
    person's name as "Last, First" — that comma must never be read as
    "multiple recipients", whether via chat_id-based classification or the
    no-chat_id recipient-count fallback."""

    def test_single_recipient_with_comma_formatted_name_no_chat_id(self):
        """Exact incident reproduction: fresh compose, no chat_id yet, a
        single recipient whose display name is comma-formatted."""
        label = _call({
            "chat_id": "",
            "chat_topic": "",
            "to": "AIAgent.ValliyappanRam@amd.com",
            "to_names": "ValliyappanRam, AI Agent",
        })
        assert label == "Direct message to ValliyappanRam, AI Agent"
        assert "Group" not in label

    def test_single_recipient_comma_name_ordinary_case(self):
        label = _call({
            "chat_id": "",
            "chat_topic": "",
            "to": "Mayuresh.Kulkarni@amd.com",
            "to_names": "Kulkarni, Mayuresh",
        })
        assert label == "Direct message to Kulkarni, Mayuresh"
        assert "Group" not in label

    def test_preview_id_with_comma_formatted_name(self):
        """Same comma-in-name trap, but with a preview chat_id present —
        must still resolve via the chat_id branch (Direct message), not
        fall through to the buggy path."""
        label = _call({
            "chat_id": "19:preview-abc123",
            "chat_topic": "ValliyappanRam,AI Agent",
            "to": "AIAgent.ValliyappanRam@amd.com",
            "to_names": "ValliyappanRam, AI Agent",
        })
        assert label.startswith("Direct message")
        assert "Group" not in label


class TestGenuineMultiRecipientIsStillGroup:
    def test_two_emails_no_chat_id_is_group(self):
        label = _call({
            "chat_id": "",
            "chat_topic": "",
            "to": "a@amd.com,b@amd.com",
            "to_names": "A, B",
        })
        assert label.startswith("Group")

    def test_thread_v2_chat_id_is_group_regardless_of_names(self):
        label = _call({
            "chat_id": "19:d3ec4168c09f4cb78792ef9702f2a963@thread.v2",
            "chat_topic": "Team Standup",
            "to": "",
            "to_names": "",
        })
        assert label.startswith("Group")

    def test_thread_skype_chat_id_is_group(self):
        label = _call({
            "chat_id": "19:abc123@thread.skype",
            "chat_topic": "Old Group Chat",
            "to": "",
            "to_names": "",
        })
        assert label.startswith("Group")


class TestMaterializedOneOnOneStillDirectMessage:
    def test_unq_gbl_spaces_chat_id_is_direct_message(self):
        label = _call({
            "chat_id": "19:58a43704-8640-49e9-a193-ac526bec1238_dc59cb67-abcd@unq.gbl.spaces",
            "chat_topic": "",
            "to": "",
            "to_names": "Valliyappan, Ram",
        })
        assert label.startswith("Direct message")
        assert "Group" not in label
