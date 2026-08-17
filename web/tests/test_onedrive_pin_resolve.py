"""Bulletproof OneDrive pinning: resolve a pinned item to a real Graph drive-item.

Graph is the source of truth for "is this id real" — we attempt a direct GET
first (with sharedWithMe fallback on 404 for SharePoint items pinned without a
drive_id), then fall back to name-search via the Microsoft Search API.
This closes the gap where pins arrive with a non-`01...`-prefixed id
(SharePoint base64url ids like "BcxSFOi...") or a fallback marker
("onedrive:filename", "SPO@{siteGuid}") and no drive_id.
"""

from unittest.mock import MagicMock, patch

import pytest


def _search_response(hits):
    """Build a Microsoft Search /search/query response envelope from resources."""
    return {"value": [{"hitsContainers": [{"hits": [{"resource": r} for r in hits]}]}]}


class _GraphError(Exception):
    def __init__(self, msg, status_code):
        super().__init__(msg)
        self.status_code = status_code


class TestIsResolvable:
    def test_graph_item_id_is_resolvable(self):
        from skills.onedrive.tools import is_resolvable_item_id

        assert is_resolvable_item_id("01S2XP2ZTRZYVYAWBMMNFJYHOHDBMMCQWI")

    def test_sharepoint_base64url_id_is_resolvable(self):
        """SharePoint ids use base64url (mixed case, '-', '_') — must not be
        rejected by the cheap filter, the direct GET decides."""
        from skills.onedrive.tools import is_resolvable_item_id

        assert is_resolvable_item_id(
            "BcxSFOiEokG2yCDVW27EbPqkJCY-BdVHuh92nXumH2KnqVx5h7oRToXNciyM"
            "-LKPGEyTkbthQUWfLaBLAPiXdw"
        )

    def test_fallback_ids_not_resolvable(self):
        from skills.onedrive.tools import is_resolvable_item_id

        assert not is_resolvable_item_id("onedrive:Presentation.pptx")
        assert not is_resolvable_item_id("SPO@3dd8961f-e488-4e60-8e11-a82d994e183d")
        assert not is_resolvable_item_id("")
        assert not is_resolvable_item_id("Deck.pptx")


class TestResolveByDirectLookup:
    """The primary resolution path: a direct Graph GET on the item_id."""

    def test_sharepoint_base64url_id_resolves_directly(self):
        """The actual bug: a SharePoint base64url id must resolve via a direct
        GET, not be rejected by a regex and forced into name-search."""
        from skills.onedrive import tools

        sp_id = (
            "BcxSFOiEokG2yCDVW27EbPqkJCY-BdVHuh92nXumH2KnqVx5h7oRToXNciyM"
            "-LKPGEyTkbthQUWfLaBLAPiXdw"
        )
        gc = MagicMock()
        gc.get.return_value = {
            "id": sp_id,
            "name": "Planning.docx",
            "webUrl": "https://amd.sharepoint.com/sites/x/Planning.docx",
            "parentReference": {"driveId": "DRV_SP"},
        }
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            out = tools.resolve_onedrive_item(
                filename="Planning.docx", item_id=sp_id, drive_id="DRV_SP"
            )
        assert out["id"] == sp_id
        assert out["drive_id"] == "DRV_SP"
        # Must have done a direct GET on /drives/{drive_id}/items/{id},
        # NOT a name-search.
        assert gc.get.call_args.args[0] == f"/drives/DRV_SP/items/{sp_id}"
        gc.post.assert_not_called()

    def test_personal_onedrive_id_resolves_via_me_drive(self):
        from skills.onedrive import tools

        gc = MagicMock()
        gc.get.return_value = {
            "id": "01ABCDEF",
            "name": "Notes.docx",
            "webUrl": "https://amd-my.sharepoint.com/Notes.docx",
            "parentReference": {"driveId": "DRV_ME"},
        }
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            out = tools.resolve_onedrive_item(filename="Notes.docx", item_id="01ABCDEF")
        assert out["id"] == "01ABCDEF"
        assert gc.get.call_args.args[0] == "/me/drive/items/01ABCDEF"
        gc.post.assert_not_called()

    def test_404_falls_back_to_sharedwithme_then_resolves(self):
        """A SharePoint item pinned without drive_id 404s on /me/drive/items,
        but sharedWithMe reveals the real drive_id."""
        from skills.onedrive import tools

        sp_id = "01SHAREPOINTITEMID"
        gc = MagicMock()

        def _get(path, params=None, **kw):
            if path == f"/me/drive/items/{sp_id}":
                raise _GraphError("not found", 404)
            if path == "/me/drive/sharedWithMe":
                return {
                    "value": [
                        {
                            "id": sp_id,
                            "name": "Shared.docx",
                            "remoteItem": {
                                "id": sp_id,
                                "parentReference": {"driveId": "DRV_SP"},
                            },
                        }
                    ]
                }
            if path == f"/drives/DRV_SP/items/{sp_id}":
                return {
                    "id": sp_id,
                    "name": "Shared.docx",
                    "webUrl": "https://amd.sharepoint.com/x/Shared.docx",
                    "parentReference": {"driveId": "DRV_SP"},
                }
            raise AssertionError(f"unexpected: {path}")

        gc.get.side_effect = _get
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            out = tools.resolve_onedrive_item(filename="Shared.docx", item_id=sp_id)
        assert out["id"] == sp_id
        assert out["drive_id"] == "DRV_SP"
        gc.post.assert_not_called()

    def test_direct_lookup_failure_falls_back_to_name_search(self):
        """If the direct GET 404s and sharedWithMe has no match, fall back to
        name-search."""
        from skills.onedrive import tools

        gc = MagicMock()

        def _get(path, params=None, **kw):
            if path == "/me/drive/items/BADID":
                raise _GraphError("not found", 404)
            if path == "/me/drive/sharedWithMe":
                return {"value": []}
            raise AssertionError(f"unexpected: {path}")

        gc.get.side_effect = _get
        gc.post.return_value = _search_response(
            [
                {
                    "name": "Found.docx",
                    "id": "01REALID",
                    "parentReference": {"driveId": "DRV_X"},
                    "webUrl": "https://x/Found.docx",
                }
            ]
        )
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            out = tools.resolve_onedrive_item(filename="Found.docx", item_id="BADID")
        assert out["id"] == "01REALID"
        # Name-search was used as the fallback.
        assert gc.post.call_args.args[0] == "/search/query"

    def test_fallback_marker_id_skips_direct_lookup(self):
        """An 'onedrive:filename' marker is not a real id — don't waste a
        network call, go straight to name-search."""
        from skills.onedrive import tools

        gc = MagicMock()
        gc.post.return_value = _search_response(
            [
                {
                    "name": "Deck.pptx",
                    "id": "01REAL",
                    "parentReference": {"driveId": "DRV"},
                    "webUrl": "https://x/Deck.pptx",
                }
            ]
        )
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            out = tools.resolve_onedrive_item(
                filename="Deck.pptx", item_id="onedrive:Deck.pptx"
            )
        assert out["id"] == "01REAL"
        # No direct GET attempted — the filter rejected the marker id.
        gc.get.assert_not_called()


class TestResolveItem:
    def test_exact_match_returns_graph_ids(self):
        from skills.onedrive import tools

        gc = MagicMock()
        gc.post.return_value = _search_response(
            [
                {
                    "name": "Other.pptx",
                    "id": "01OTHERAAAAAAAAAAAAAAAAAAAAAA",
                    "parentReference": {"driveId": "DRV_X"},
                    "webUrl": "https://x/Other.pptx",
                },
                {
                    "name": "ROCmAi Release Review.pptx",
                    "id": "01REALBBBBBBBBBBBBBBBBBBBBBB",
                    "parentReference": {"driveId": "DRV_SP"},
                    "webUrl": "https://amd.sharepoint.com/sites/AIGROCm/Release.pptx",
                },
            ]
        )
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            out = tools.resolve_onedrive_item("ROCmAi Release Review.pptx")
        assert out["id"] == "01REALBBBBBBBBBBBBBBBBBBBBBB"
        assert out["drive_id"] == "DRV_SP"
        assert "Release" in out["web_url"]
        # Must have queried the cross-tenant Search API, not /me/drive.
        assert gc.post.call_args.args[0] == "/search/query"

    def test_location_hint_disambiguates_same_name(self):
        from skills.onedrive import tools

        gc = MagicMock()
        gc.post.return_value = _search_response(
            [
                {
                    "name": "Deck.pptx",
                    "id": "01AAAAAAAAAAAAAAAAAAAAAAAAAA",
                    "parentReference": {"driveId": "DRV_A"},
                    "webUrl": "https://amd.sharepoint.com/sites/TeamA/Deck.pptx",
                },
                {
                    "name": "Deck.pptx",
                    "id": "01BBBBBBBBBBBBBBBBBBBBBBBBBB",
                    "parentReference": {"driveId": "DRV_B"},
                    "webUrl": "https://amd.sharepoint.com/sites/TeamB/Deck.pptx",
                },
            ]
        )
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            out = tools.resolve_onedrive_item("Deck.pptx", location_hint="TeamB")
        assert out["id"] == "01BBBBBBBBBBBBBBBBBBBBBBBBBB"

    def test_no_match_returns_error(self):
        from skills.onedrive import tools

        gc = MagicMock()
        gc.post.return_value = _search_response([])
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            out = tools.resolve_onedrive_item("Nonexistent.pptx")
        assert "error" in out

    def test_ambiguous_no_exact_returns_error(self):
        from skills.onedrive import tools

        gc = MagicMock()
        # Two different files, neither an exact match for the query.
        gc.post.return_value = _search_response(
            [
                {
                    "name": "Deck v1.pptx",
                    "id": "01AAAAAAAAAAAAAAAAAAAAAAAAAA",
                    "parentReference": {"driveId": "DRV_A"},
                    "webUrl": "https://x/1",
                },
                {
                    "name": "Deck v2.pptx",
                    "id": "01BBBBBBBBBBBBBBBBBBBBBBBBBB",
                    "parentReference": {"driveId": "DRV_B"},
                    "webUrl": "https://x/2",
                },
            ]
        )
        with patch("skills._m365.helpers.get_skill_client", return_value=gc):
            out = tools.resolve_onedrive_item("Deck.pptx")
        assert "error" in out
