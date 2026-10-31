import pytest

from backend.app import service as service_module
from backend.app.service import Cancelled, Service


@pytest.fixture
def service(tmp_path):
    instance = Service(tmp_path / "managed")
    try:
        yield instance
    finally:
        instance.close()


def test_snapshot_file_and_chunk_updates_share_four_per_second_limit(service, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(service_module.time, "monotonic", lambda: clock[0])
    job = service.store.put("job", {"id": "sampled-job", "state": "queued"})
    for index in range(100):
        clock[0] = index / 100
        phase = "snapshotting sources" if index % 2 == 0 else "snapshotting opaque bytes"
        service._checkpoint(job, phase, index, 100)
    events = service.store.events(job["id"])
    assert len(events) == 4
    assert [event["data"]["progress"]["completed"] for event in events] == [0, 25, 50, 75]
    assert service.store.get("job", job["id"])["progress"]["completed"] == 75
    assert job["progress"]["completed"] == 99
    service._checkpoint(job, "analyzing frozen snapshot", 100, 100)
    assert service.store.get("job", job["id"])["progress"]["completed"] == 100
    assert service.store.events(job["id"])[-1]["data"]["phase"] == "analyzing frozen snapshot"
    service._checkpoint(job, "snapshotting sources", 0, 10)
    assert len(service.store.events(job["id"])) == 6


def test_cancellation_is_checked_even_when_progress_would_be_suppressed(service, monkeypatch):
    monkeypatch.setattr(service_module.time, "monotonic", lambda: 0.0)
    job = service.store.put("job", {"id": "cancel-sample", "state": "queued"})
    service._checkpoint(job, "snapshotting sources", 0, 5)
    service.cancelled.add(job["id"])
    with pytest.raises(Cancelled):
        service._checkpoint(job, "snapshotting opaque bytes", 1, 5)
    assert len(service.store.events(job["id"])) == 1


@pytest.mark.parametrize("outcome", ["completed", "cancelled", "failed"])
def test_run_always_persists_terminal_state_after_suppressed_samples(service, monkeypatch, outcome):
    monkeypatch.setattr(service_module.time, "monotonic", lambda: 0.0)
    workspace = service.store.list("workspace")[0]
    job = service.store.put("job", {"id": "terminal-" + outcome, "state": "queued",
                                    "command": "snapshot_fixture"})
    service.store.append_event(job["id"], job)

    def snapshot_fixture(_workspace, _payload, checkpoint):
        for index in range(10):
            checkpoint("snapshotting sources" if index % 2 == 0 else "snapshotting opaque bytes", index, 10)
        if outcome == "cancelled":
            service.cancelled.add(job["id"])
            checkpoint("snapshotting opaque bytes", 10, 10)
        if outcome == "failed":
            raise ValueError("synthetic capture failure")
        return {"fixture_complete": True}

    monkeypatch.setattr(service, "_snapshot_fixture", snapshot_fixture, raising=False)
    service._run(job, workspace, {})
    stored = service.store.get("job", job["id"])
    events = service.store.events(job["id"])
    assert stored["state"] == outcome and events[-1]["data"]["state"] == outcome
    assert [event["data"]["state"] for event in events] == ["queued", "running", "running", outcome]
    assert stored["progress"]["completed"] == 9
    assert job["id"] not in service.cancelled
