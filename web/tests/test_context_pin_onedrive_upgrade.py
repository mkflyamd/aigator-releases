"""POST /api/context/pin upgrades a non-resolvable OneDrive pin to a real Graph
id at pin time, so the persisted pin resolves directly on read.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app


class TestPinUpgrade:
    def test_onedrive_fallback_id_is_upgraded(self):
        client = TestClient(app)
        captured = {}

        def _fake_set_pin(source, item_id, label, meta, context_id):
            captured["source"] = source
            captured["id"] = item_id
            captured["meta"] = meta
            return {"pinned": True, "id": item_id}

        resolved = {
            "id": "01REALIDXXXXXXXXXXXXXXXXXXXX",
            "drive_id": "DRV_SP",
            "web_url": "https://amd.sharepoint.com/sites/x/Deck.pptx",
            "name": "Deck.pptx",
        }

        with (
            patch("skills.context.state.set_pin", side_effect=_fake_set_pin),
            patch("skills.onedrive.tools.resolve_onedrive_item", return_value=resolved),
        ):
            r = client.post(
                "/api/context/pin",
                json={
                    "source": "onedrive",
                    "id": "onedrive:Deck.pptx",
                    "label": "Deck.pptx",
                    "meta": {"file_path": "Deck.pptx", "location": "AIG ROCm"},
                    "context_id": "t1",
                },
            )
        assert r.status_code == 200, r.text
        # The persisted id must be the resolved Graph id, not the fallback.
        assert captured["id"] == "01REALIDXXXXXXXXXXXXXXXXXXXX"
        assert captured["meta"]["drive_id"] == "DRV_SP"
        assert captured["meta"]["resolved_at_pin"] is True

    def test_already_resolvable_id_is_kept(self):
        """A pin with a real Graph id + drive_id must be kept as-is — the
        resolver does a direct GET (which succeeds) and returns the same id,
        never falling back to name-search."""
        client = TestClient(app)
        captured = {}

        def _fake_set_pin(source, item_id, label, meta, context_id):
            captured["id"] = item_id
            captured["meta"] = meta
            return {"pinned": True, "id": item_id}

        # Direct lookup succeeds — returns the same id back.
        resolved = {
            "id": "01ALREADYGOODXXXXXXXXXXXXXXX",
            "drive_id": "DRV_SP",
            "web_url": "https://x/Deck.pptx",
            "name": "Deck.pptx",
        }
        with (
            patch("skills.context.state.set_pin", side_effect=_fake_set_pin),
            patch(
                "skills.onedrive.tools.resolve_onedrive_item", return_value=resolved
            ) as mock_resolve,
        ):
            r = client.post(
                "/api/context/pin",
                json={
                    "source": "onedrive",
                    "id": "01ALREADYGOODXXXXXXXXXXXXXXX",
                    "label": "Deck.pptx",
                    "meta": {"drive_id": "DRV_SP"},
                    "context_id": "t1",
                },
            )
        assert r.status_code == 200, r.text
        # The id is preserved unchanged.
        assert captured["id"] == "01ALREADYGOODXXXXXXXXXXXXXXX"
        # The resolver WAS called (Graph is the source of truth, not regex),
        # but it only did a direct GET — no name-search fallback was needed.
        mock_resolve.assert_called_once()

    def test_resolution_failure_still_pins_fallback(self):
        """If resolution fails, the pin must still persist (never block a pin)."""
        client = TestClient(app)
        captured = {}

        def _fake_set_pin(source, item_id, label, meta, context_id):
            captured["id"] = item_id
            return {"pinned": True, "id": item_id}

        with (
            patch("skills.context.state.set_pin", side_effect=_fake_set_pin),
            patch(
                "skills.onedrive.tools.resolve_onedrive_item",
                return_value={"error": "no match"},
            ),
        ):
            r = client.post(
                "/api/context/pin",
                json={
                    "source": "onedrive",
                    "id": "onedrive:Deck.pptx",
                    "label": "Deck.pptx",
                    "meta": {"file_path": "Deck.pptx"},
                    "context_id": "t1",
                },
            )
        assert r.status_code == 200, r.text
        # Falls back to the original id — the read-time search still handles it.
        assert captured["id"] == "onedrive:Deck.pptx"
