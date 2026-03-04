"""Tests for POST /agent/stream — Agent tab SSE (staged papers + model only)."""

import json
from unittest.mock import patch

from src.api.schemas import CorrelateResult, NudgeResult


def test_agent_stream_returns_sse_with_mocked_synthesis(client):
    """Stream yields start, reasoning-delta, text-start, text-delta, text-end, data-heaven-research, finish, [DONE]."""
    body = (
        "REASONING:\nI will write a greeting.\n\n"
        "DOCUMENT_CONTENT:\n\nHello from agent.\n\n"
        "HEAVEN_NOTE:\nDone."
    )

    def fake_stream(*_args, **_kwargs):
        yield body

    with patch("src.api.routers.agent.stream_agent_synthesis", side_effect=fake_stream):
        with client.stream("POST", "/agent/stream", json={"query": "Say hello", "staged_paper_ids": [], "canvas_summary": ""}) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            lines = []
            for line in resp.iter_lines():
                if line:
                    lines.append(line.decode("utf-8") if isinstance(line, bytes) else line)

    data_lines = [ln for ln in lines if ln.startswith("data:")]
    events = []
    for ln in data_lines:
        payload = ln[5:].strip()
        if payload == "[DONE]":
            events.append("[DONE]")
            continue
        try:
            obj = json.loads(payload)
            events.append(obj.get("type", ""))
        except json.JSONDecodeError:
            pass

    assert "start" in events
    assert "data-heaven-research" in events
    assert "finish" in events
    assert "[DONE]" in events

    # data-heaven-research should contain parsed report, note, and reasoning
    for ln in data_lines:
        if "[DONE]" in ln:
            continue
        try:
            obj = json.loads(ln[5:].strip())
            if obj.get("type") == "data-heaven-research" and obj.get("data"):
                d = obj["data"]
                assert "Hello from agent" in (d.get("report") or "")
                assert d.get("heaven_note") == "Done."
                assert "greeting" in (d.get("reasoning") or "")
                break
        except json.JSONDecodeError:
            pass


def test_agent_stream_without_reasoning_section(client):
    """Stream still works when model omits REASONING section."""
    body = "DOCUMENT_CONTENT:\n\nHello from agent.\n\nHEAVEN_NOTE:\nDone."

    def fake_stream(*_args, **_kwargs):
        yield body

    with patch("src.api.routers.agent.stream_agent_synthesis", side_effect=fake_stream):
        with client.stream("POST", "/agent/stream", json={"query": "Say hello", "staged_paper_ids": [], "canvas_summary": ""}) as resp:
            assert resp.status_code == 200
            lines = []
            for line in resp.iter_lines():
                if line:
                    lines.append(line.decode("utf-8") if isinstance(line, bytes) else line)

    data_lines = [ln for ln in lines if ln.startswith("data:")]
    events = []
    for ln in data_lines:
        payload = ln[5:].strip()
        if payload == "[DONE]":
            events.append("[DONE]")
            continue
        try:
            obj = json.loads(payload)
            events.append(obj.get("type", ""))
        except json.JSONDecodeError:
            pass

    assert "start" in events
    assert "data-heaven-research" in events
    assert "finish" in events


def test_agent_stream_verification_and_correlation_when_report_and_staged_ids(client):
    """When report and staged_paper_ids are present, stream includes verification/correlation events."""
    body = (
        "REASONING:\nAnalyzing the topic.\n\n"
        "DOCUMENT_CONTENT:\n\nA paragraph here with enough text to trigger nudge and correlate.\n\n"
        "Another block of content that is also long enough for the API to process.\n\n"
        "HEAVEN_NOTE:\nDone."
    )

    def fake_stream(*_args, **_kwargs):
        yield body

    nudge_result = NudgeResult(nudges=[])
    corr_result = CorrelateResult(correlations=[])

    with (
        patch("src.api.routers.agent.stream_agent_synthesis", side_effect=fake_stream),
        patch("src.api.routers.agent._load_staged_papers", return_value=[{"title": "T", "concepts": []}]),
        patch("src.api.routers.agent.get_nudges", return_value=nudge_result),
        patch("src.api.routers.agent.get_correlations", return_value=corr_result),
    ):
        with client.stream(
            "POST",
            "/agent/stream",
            json={"query": "Write something", "staged_paper_ids": ["paper-1"], "canvas_summary": ""},
        ) as resp:
            assert resp.status_code == 200
            lines = []
            for line in resp.iter_lines():
                if line:
                    lines.append(line.decode("utf-8") if isinstance(line, bytes) else line)

    data_lines = [ln for ln in lines if ln.startswith("data:")]
    types = []
    for ln in data_lines:
        payload = ln[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
            types.append(obj.get("type", ""))
        except json.JSONDecodeError:
            pass

    assert "data-heaven-research" in types
    assert "finish" in types
