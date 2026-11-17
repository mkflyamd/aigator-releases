import asyncio
import io
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))

from routes import onedrive as route  # noqa: E402


class Err(Exception):
    def __init__(self, status_code):
        super().__init__(f"Graph API {status_code}")
        self.status_code = status_code


class FakeGC:
    def __init__(self, put_error=None):
        self.put_error = put_error
        self.puts = 0

    def put_binary(self, path, data, content_type="application/octet-stream"):
        self.puts += 1
        if self.put_error:
            raise self.put_error
        return {"id": "N1"}

    def post(self, path, body):
        return {"link": {"webUrl": "https://od/a"}}


def _upload(monkeypatch, gc, handler, *args):
    monkeypatch.setattr("skills._m365.helpers.get_graph_client", lambda: gc)
    f = UploadFile(file=io.BytesIO(b"hello"), filename="a.txt")
    return asyncio.run(handler(*args, f))


@pytest.mark.parametrize("handler,args", [(route.onedrive_upload_to_folder, ("F1",)), (route.upload_to_onedrive, ())])
@pytest.mark.parametrize("error", [Err(500), Err(503), Err(504), RuntimeError("Network error on PUT: timed out")])
def test_an_upload_with_no_clear_answer_says_the_file_may_have_landed(monkeypatch, handler, args, error):
    gc = FakeGC(put_error=error)
    with pytest.raises(HTTPException) as e:
        _upload(monkeypatch, gc, handler, *args)
    assert e.value.status_code == 502 and "may already be uploaded" in e.value.detail
    assert gc.puts == 1


@pytest.mark.parametrize("handler,args", [(route.onedrive_upload_to_folder, ("F1",)), (route.upload_to_onedrive, ())])
def test_an_upload_the_server_refused_keeps_its_own_message(monkeypatch, handler, args):
    with pytest.raises(HTTPException) as e:
        _upload(monkeypatch, FakeGC(put_error=Err(403)), handler, *args)
    assert e.value.status_code == 500 and "403" in e.value.detail
