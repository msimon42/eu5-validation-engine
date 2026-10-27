import asyncio
import json

from backend.app.main import BodyBudgetMiddleware


def execute(chunks, headers=()):
    called, sent = [], []

    async def application(scope, receive, send):
        called.append(await receive())

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(BodyBudgetMiddleware(application, limit=4)({"type": "http", "method": "POST", "headers": list(headers)}, receive, send))
    return called, sent


def test_actual_chunked_bytes_are_bounded_without_length():
    called, sent = execute([{"type": "http.request", "body": b"123", "more_body": True}, {"type": "http.request", "body": b"45", "more_body": False}])
    assert called == []
    assert sent[0]["status"] == 413


def test_bad_content_length_fails_without_reading():
    called, sent = execute([], [(b"content-length", b"invalid")])
    assert called == []
    assert sent[0]["status"] == 413
    assert "detail" in json.loads(sent[1]["body"])


def test_small_chunks_are_replayed_exactly():
    called, sent = execute([{"type": "http.request", "body": b"12", "more_body": True}, {"type": "http.request", "body": b"34", "more_body": False}])
    assert called == [{"type": "http.request", "body": b"1234", "more_body": False}]
    assert sent == []
