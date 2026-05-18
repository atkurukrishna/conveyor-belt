"""Tests for the FastAPI server and WebSocket pipeline."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from conveyor_belt.models import Finding, Severity, StationResult
from conveyor_belt.server import RunRequest, _broadcast, _execute, _runs, _sockets, app

# ── Helpers ────────────────────────────────────────────────────────────────


def _clear_state() -> None:
    _runs.clear()
    _sockets.clear()


# ── REST endpoint tests ────────────────────────────────────────────────────


class TestIndexEndpoint:
    def test_serves_html(self):
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestListRuns:
    def setup_method(self):
        _clear_state()

    def test_empty_initially(self):
        client = TestClient(app)
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_existing_runs(self):
        _runs["abc"] = {"id": "abc", "status": "pending"}
        client = TestClient(app)
        resp = client.get("/api/runs")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "abc"


class TestGetRun:
    def setup_method(self):
        _clear_state()

    def test_not_found(self):
        client = TestClient(app)
        resp = client.get("/api/runs/nonexistent")
        assert resp.json() == {"error": "not found"}

    def test_found(self):
        _runs["xyz"] = {"id": "xyz", "status": "complete"}
        client = TestClient(app)
        resp = client.get("/api/runs/xyz")
        assert resp.json()["status"] == "complete"


class TestCreateRun:
    def setup_method(self):
        _clear_state()

    def test_returns_run_id(self):
        with patch("conveyor_belt.server.asyncio.create_task"):
            client = TestClient(app)
            resp = client.post("/api/runs", json={"repo": ".", "diff": "HEAD~1"})
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data
        run_id = data["run_id"]
        assert _runs[run_id]["status"] == "pending"
        assert _runs[run_id]["diff"] == "HEAD~1"

    def test_stores_pr_number(self):
        with patch("conveyor_belt.server.asyncio.create_task"):
            client = TestClient(app)
            resp = client.post("/api/runs", json={"repo": ".", "pr": 42})
        run_id = resp.json()["run_id"]
        assert _runs[run_id]["pr"] == 42


# ── WebSocket tests ────────────────────────────────────────────────────────


class TestWebSocket:
    def setup_method(self):
        _clear_state()

    def test_connect_unknown_run_rejected(self):
        """Unknown run_id is rejected with close code 4404."""
        client = TestClient(app)
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/unknown-run") as ws:
                ws.receive_text()

    def test_connect_sends_existing_state(self):
        _runs["run1"] = {"id": "run1", "status": "complete", "stations": {}}
        client = TestClient(app)
        with client.websocket_connect("/ws/run1") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "state"
            assert msg["data"]["status"] == "complete"


# ── _broadcast helper ──────────────────────────────────────────────────────


class TestBroadcast:
    def setup_method(self):
        _clear_state()

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        ws1 = MagicMock()
        ws1.send_text = AsyncMock()
        ws2 = MagicMock()
        ws2.send_text = AsyncMock()
        _sockets["r1"] = [ws1, ws2]

        await _broadcast("r1", {"type": "ping"})

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_broadcast_drops_dead_socket(self):
        ws_dead = MagicMock()
        ws_dead.send_text = AsyncMock(side_effect=RuntimeError("closed"))
        ws_ok = MagicMock()
        ws_ok.send_text = AsyncMock()
        _sockets["r2"] = [ws_dead, ws_ok]

        await _broadcast("r2", {"type": "ping"})

        assert ws_dead not in _sockets["r2"]
        assert ws_ok in _sockets["r2"]

    @pytest.mark.asyncio
    async def test_broadcast_unknown_run_is_noop(self):
        # Should not raise even when the run has no registered sockets
        await _broadcast("no-such-run", {"type": "ping"})


# ── _execute pipeline tests ────────────────────────────────────────────────


def _make_station_result(name: str, passed: bool = True) -> StationResult:
    return StationResult(station_name=name, passed=passed, summary="ok", duration_seconds=0.1)


def _make_mock_config(policy: str = "hard_fail"):
    cfg = MagicMock()
    cfg.project.languages = ["python"]
    cfg.gate.policy = policy
    return cfg


class TestExecutePipeline:
    def setup_method(self):
        _clear_state()

    @pytest.mark.asyncio
    async def test_successful_run_with_diff(self, tmp_path):
        run_id = "test-run-1"
        _runs[run_id] = {"id": run_id, "status": "pending", "stations": {}, "report": None, "error": None}
        _sockets[run_id] = []

        cfg = _make_mock_config()
        mock_station = MagicMock()
        mock_station.execute = AsyncMock(return_value=_make_station_result("idiomatic"))

        with (
            patch("conveyor_belt.server.load_config", return_value=cfg),
            patch("conveyor_belt.server._available_stations", return_value={"idiomatic": mock_station}),
            patch("conveyor_belt.integrations.git.changed_files_from_diff", new_callable=AsyncMock, return_value=[]),
        ):
            req = RunRequest(repo=str(tmp_path), diff="HEAD~1")
            await _execute(run_id, req)

        assert _runs[run_id]["status"] == "complete"
        assert _runs[run_id]["report"]["gate_passed"] is True
        assert _runs[run_id]["stations"]["idiomatic"]["status"] == "complete"

    @pytest.mark.asyncio
    async def test_gate_fails_when_station_fails(self, tmp_path):
        run_id = "test-run-2"
        _runs[run_id] = {"id": run_id, "status": "pending", "stations": {}, "report": None, "error": None}
        _sockets[run_id] = []

        cfg = _make_mock_config("hard_fail")
        mock_station = MagicMock()
        mock_station.execute = AsyncMock(return_value=_make_station_result("security", passed=False))

        with (
            patch("conveyor_belt.server.load_config", return_value=cfg),
            patch("conveyor_belt.server._available_stations", return_value={"security": mock_station}),
            patch("conveyor_belt.integrations.git.changed_files_from_diff", new_callable=AsyncMock, return_value=[]),
        ):
            req = RunRequest(repo=str(tmp_path), diff="HEAD~1")
            await _execute(run_id, req)

        assert _runs[run_id]["report"]["gate_passed"] is False

    @pytest.mark.asyncio
    async def test_soft_fail_policy_always_passes(self, tmp_path):
        run_id = "test-run-3"
        _runs[run_id] = {"id": run_id, "status": "pending", "stations": {}, "report": None, "error": None}
        _sockets[run_id] = []

        cfg = _make_mock_config("soft_fail")
        mock_station = MagicMock()
        mock_station.execute = AsyncMock(return_value=_make_station_result("security", passed=False))

        with (
            patch("conveyor_belt.server.load_config", return_value=cfg),
            patch("conveyor_belt.server._available_stations", return_value={"security": mock_station}),
            patch("conveyor_belt.integrations.git.changed_files_from_diff", new_callable=AsyncMock, return_value=[]),
        ):
            req = RunRequest(repo=str(tmp_path), diff="HEAD~1")
            await _execute(run_id, req)

        assert _runs[run_id]["report"]["gate_passed"] is True

    @pytest.mark.asyncio
    async def test_no_stations_completes_immediately(self, tmp_path):
        run_id = "test-run-4"
        _runs[run_id] = {"id": run_id, "status": "pending", "stations": {}, "report": None, "error": None}
        _sockets[run_id] = []

        cfg = _make_mock_config()
        with (
            patch("conveyor_belt.server.load_config", return_value=cfg),
            patch("conveyor_belt.server._available_stations", return_value={}),
            patch("conveyor_belt.integrations.git.changed_files_from_diff", new_callable=AsyncMock, return_value=[]),
        ):
            req = RunRequest(repo=str(tmp_path), diff="HEAD~1")
            await _execute(run_id, req)

        assert _runs[run_id]["status"] == "complete"
        assert _runs[run_id]["report"]["gate_passed"] is True

    @pytest.mark.asyncio
    async def test_uses_staged_when_no_pr_or_diff(self, tmp_path):
        run_id = "test-run-5"
        _runs[run_id] = {"id": run_id, "status": "pending", "stations": {}, "report": None, "error": None}
        _sockets[run_id] = []

        cfg = _make_mock_config()
        with (
            patch("conveyor_belt.server.load_config", return_value=cfg),
            patch("conveyor_belt.server._available_stations", return_value={}),
            patch(
                "conveyor_belt.integrations.git.changed_files_from_staged",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_staged,
        ):
            req = RunRequest(repo=str(tmp_path))
            await _execute(run_id, req)

        mock_staged.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_station_crash_recorded_as_failed(self, tmp_path):
        run_id = "test-run-6"
        _runs[run_id] = {"id": run_id, "status": "pending", "stations": {}, "report": None, "error": None}
        _sockets[run_id] = []

        cfg = _make_mock_config()
        mock_station = MagicMock()
        mock_station.execute = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch("conveyor_belt.server.load_config", return_value=cfg),
            patch("conveyor_belt.server._available_stations", return_value={"security": mock_station}),
            patch("conveyor_belt.integrations.git.changed_files_from_diff", new_callable=AsyncMock, return_value=[]),
        ):
            req = RunRequest(repo=str(tmp_path), diff="HEAD~1")
            await _execute(run_id, req)

        assert _runs[run_id]["stations"]["security"]["result"]["passed"] is False
        assert "boom" in _runs[run_id]["stations"]["security"]["result"]["summary"]

    @pytest.mark.asyncio
    async def test_top_level_error_sets_error_status(self, tmp_path):
        run_id = "test-run-7"
        _runs[run_id] = {"id": run_id, "status": "pending", "stations": {}, "report": None, "error": None}
        _sockets[run_id] = []

        with patch("conveyor_belt.server.load_config", side_effect=RuntimeError("bad config")):
            req = RunRequest(repo=str(tmp_path), diff="HEAD~1")
            await _execute(run_id, req)

        assert _runs[run_id]["status"] == "error"
        assert "bad config" in _runs[run_id]["error"]

    @pytest.mark.asyncio
    async def test_station_subset_filter(self, tmp_path):
        run_id = "test-run-8"
        _runs[run_id] = {"id": run_id, "status": "pending", "stations": {}, "report": None, "error": None}
        _sockets[run_id] = []

        cfg = _make_mock_config()
        st_a = MagicMock()
        st_a.execute = AsyncMock(return_value=_make_station_result("idiomatic"))
        st_b = MagicMock()
        st_b.execute = AsyncMock(return_value=_make_station_result("security"))

        with (
            patch("conveyor_belt.server.load_config", return_value=cfg),
            patch("conveyor_belt.server._available_stations", return_value={"idiomatic": st_a, "security": st_b}),
            patch("conveyor_belt.integrations.git.changed_files_from_diff", new_callable=AsyncMock, return_value=[]),
        ):
            req = RunRequest(repo=str(tmp_path), diff="HEAD~1", stations=["idiomatic"])
            await _execute(run_id, req)

        assert "idiomatic" in _runs[run_id]["stations"]
        assert "security" not in _runs[run_id]["stations"]

    @pytest.mark.asyncio
    async def test_findings_serialised_in_result(self, tmp_path):
        run_id = "test-run-9"
        _runs[run_id] = {"id": run_id, "status": "pending", "stations": {}, "report": None, "error": None}
        _sockets[run_id] = []

        cfg = _make_mock_config()
        result_with_findings = StationResult(
            station_name="security",
            passed=False,
            summary="1 finding",
            findings=[Finding(rule="B602", severity=Severity.HIGH, message="shell injection")],
        )
        mock_station = MagicMock()
        mock_station.execute = AsyncMock(return_value=result_with_findings)

        with (
            patch("conveyor_belt.server.load_config", return_value=cfg),
            patch("conveyor_belt.server._available_stations", return_value={"security": mock_station}),
            patch("conveyor_belt.integrations.git.changed_files_from_diff", new_callable=AsyncMock, return_value=[]),
        ):
            req = RunRequest(repo=str(tmp_path), diff="HEAD~1")
            await _execute(run_id, req)

        findings = _runs[run_id]["stations"]["security"]["result"]["findings"]
        assert len(findings) == 1
        assert findings[0]["rule"] == "B602"
