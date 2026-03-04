"""Tests for POST /chat."""

import json
from unittest.mock import MagicMock, patch

from src.model.providers.base import LLMResponse


def _llm_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="mock", input_tokens=10, output_tokens=5)


def _llm_json(reply: str, action=None) -> str:
    return json.dumps({"reply": reply, "action": action})


# ---------------------------------------------------------------------------
# Basic flow
# ---------------------------------------------------------------------------

def test_chat_returns_reply_and_session_id(client):
    payload = _llm_json("Hello mathematician!")
    with patch("src.api.routers.chat.primary.complete", return_value=_llm_response(payload)):
        resp = client.post("/chat", json={"message": "Hi"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "Hello mathematician!"
    assert "session_id" in data
    assert data["canvas_items"] == []


def test_chat_session_id_reused(client):
    payload = _llm_json("First reply")
    with patch("src.api.routers.chat.primary.complete", return_value=_llm_response(payload)):
        r1 = client.post("/chat", json={"message": "msg1"})
    session_id = r1.json()["session_id"]

    payload2 = _llm_json("Second reply")
    with patch("src.api.routers.chat.primary.complete", return_value=_llm_response(payload2)):
        r2 = client.post("/chat", json={"message": "msg2", "session_id": session_id})
    assert r2.json()["session_id"] == session_id


def test_chat_plain_text_fallback(client):
    """LLM returns non-JSON — used as reply directly."""
    with patch("src.api.routers.chat.primary.complete", return_value=_llm_response("plain text")):
        resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "plain text"


# ---------------------------------------------------------------------------
# Write actions — executed immediately, canvas_items returned
# ---------------------------------------------------------------------------

def test_chat_ingest_paper_action_executed(client):
    """ingest_paper action executes; reply reflects result; canvas_items contains paper placeholder."""
    action = {"type": "ingest_paper", "payload": {"arxiv_id": "2301.00001"}}
    payload = _llm_json("I will ingest that paper.", action)
    mock_meta = MagicMock(
        arxiv_id="2301.00001",
        title="Test Paper",
        authors=["Author One"],
        abstract="Abstract text.",
        url="https://arxiv.org/abs/2301.00001",
        published_at=None,
        msc_codes=[],
    )
    with (
        patch("src.api.routers.chat.primary.complete", return_value=_llm_response(payload)),
        patch("src.api.routers.chat.arxiv_client.fetch_by_id", return_value=mock_meta),
        patch("src.api.routers.chat.collections.upsert_paper"),
        patch("asyncio.create_task"),
    ):
        resp = client.post("/chat", json={"message": "Ingest 2301.00001"})
    data = resp.json()
    assert resp.status_code == 200
    assert "Test Paper" in data["reply"]
    # canvas_items should contain a paper placeholder
    assert any(item["type"] == "paper" for item in data["canvas_items"])


def test_chat_create_discovery_action_executed(client):
    """create_discovery action spawns background task; reply confirms start; canvas_items is empty."""
    action = {
        "type": "create_discovery",
        "payload": {
            "name": "Generalised RH",
            "base_concept_id": "some-id",
            "modified_latex_statement": r"L(s,\chi) \neq 0",
            "modification_description": "Extend to Dirichlet L-functions.",
        },
    }
    payload = _llm_json("Here is the modified statement.", action)
    with (
        patch("src.api.routers.chat.primary.complete", return_value=_llm_response(payload)),
        patch("asyncio.create_task"),
    ):
        resp = client.post("/chat", json={"message": "What if RH held for all L-functions?"})
    data = resp.json()
    assert resp.status_code == 200
    assert "Generalised RH" in data["reply"]
    assert isinstance(data["canvas_items"], list)


# ---------------------------------------------------------------------------
# Read actions — executed immediately
# ---------------------------------------------------------------------------

def test_chat_search_concepts_executes_and_appends(client):
    action = {"type": "search_concepts", "payload": {"query": "Riemann", "n_results": 3}}
    llm_payload = _llm_json("Found these:", action)
    mock_chroma = {
        "ids": [["cid1"]],
        "distances": [[0.05]],
        "metadatas": [[{"name": "RH", "concept_type": "theorem"}]],
    }
    with (
        patch("src.api.routers.chat.primary.complete", return_value=_llm_response(llm_payload)),
        patch("src.api.routers.chat.collections.query_concepts", return_value=mock_chroma),
    ):
        resp = client.post("/chat", json={"message": "Find RH"})
    data = resp.json()
    assert "RH" in data["reply"]
    # canvas_items should contain the matched concept
    assert any(item["id"] == "cid1" for item in data["canvas_items"])


def test_chat_unknown_action_type_ignored(client):
    action = {"type": "delete_everything", "payload": {}}
    payload = _llm_json("Hmm.", action)
    with patch("src.api.routers.chat.primary.complete", return_value=_llm_response(payload)):
        resp = client.post("/chat", json={"message": "Do something weird"})
    data = resp.json()
    assert data["reply"] == "Hmm."
    assert data["canvas_items"] == []


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_chat_llm_error_returns_503(client):
    with patch("src.api.routers.chat.primary.complete", side_effect=RuntimeError("timeout")):
        resp = client.post("/chat", json={"message": "hi"})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# History truncation
# ---------------------------------------------------------------------------

def test_chat_history_truncation(client, test_sessions):
    """Stored session history never exceeds _MAX_HISTORY_TURNS after truncation."""
    from src.api.routers.chat import _MAX_HISTORY_TURNS

    # Send enough messages to exceed the limit — each round trip adds 2 entries
    # (one user, one assistant), so _MAX_HISTORY_TURNS // 2 + 2 rounds guarantees overflow.
    turns = _MAX_HISTORY_TURNS // 2 + 2
    session_id = None
    for i in range(turns):
        payload = _llm_json(f"Reply {i}")
        body: dict = {"message": f"Message {i}"}
        if session_id:
            body["session_id"] = session_id
        with patch("src.api.routers.chat.primary.complete", return_value=_llm_response(payload)):
            resp = client.post("/chat", json=body)
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

    assert session_id in test_sessions
    assert len(test_sessions[session_id]) <= _MAX_HISTORY_TURNS
