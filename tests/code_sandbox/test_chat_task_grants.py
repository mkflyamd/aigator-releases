from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import conversation_routes
from sandbox import task_grants


def test_closing_a_tab_ends_that_tabs_grants_only():
    app = FastAPI()
    app.include_router(conversation_routes.router)
    task_grants._reset()
    task_grants.add("tab-a", [], ["/proj"], ["h.example:443"])
    task_grants.add("tab-b", [], ["/proj"], [])
    assert TestClient(app).delete("/api/conversation/tab-a").status_code == 200
    assert not task_grants.covers("tab-a", [], ["/proj"], [])
    assert task_grants.covers("tab-b", [], ["/proj"], [])
    task_grants._reset()
