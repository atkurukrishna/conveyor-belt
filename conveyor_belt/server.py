"""FastAPI web server — visual dashboard for the Conveyor Belt QA pipeline."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from conveyor_belt.config import load_config
from conveyor_belt.context import StationContext
from conveyor_belt.models import StationResult
from conveyor_belt.orchestrator import _available_stations

_STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Conveyor Belt QA")
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(_STATIC / "index.html"))


# ── In-memory run store ────────────────────────────────────────────────

_runs: dict[str, dict[str, Any]] = {}
_sockets: dict[str, list[WebSocket]] = {}


# ── Request / Response models ──────────────────────────────────────────


class RunRequest(BaseModel):
    repo: str = "."
    pr: int | None = None
    diff: str | None = None
    config_path: str | None = None
    stations: list[str] = []


# ── REST endpoints ─────────────────────────────────────────────────────


@app.get("/api/runs")
async def list_runs() -> list[dict]:
    return list(_runs.values())


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    return _runs.get(run_id, {"error": "not found"})


@app.post("/api/runs")
async def create_run(req: RunRequest) -> dict[str, str]:
    run_id = str(uuid.uuid4())
    _runs[run_id] = {
        "id": run_id,
        "status": "pending",
        "repo": req.repo,
        "pr": req.pr,
        "diff": req.diff,
        "stations": {},
        "report": None,
        "error": None,
    }
    _sockets[run_id] = []
    asyncio.create_task(_execute(run_id, req))
    return {"run_id": run_id}


# ── WebSocket ──────────────────────────────────────────────────────────


@app.websocket("/ws/{run_id}")
async def ws_endpoint(ws: WebSocket, run_id: str) -> None:
    await ws.accept()
    _sockets.setdefault(run_id, []).append(ws)
    if run_id in _runs:
        await _send(ws, {"type": "state", "data": _runs[run_id]})
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        if ws in _sockets.get(run_id, []):
            _sockets[run_id].remove(ws)


async def _broadcast(run_id: str, msg: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in list(_sockets.get(run_id, [])):
        try:
            await _send(ws, msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _sockets.get(run_id, []):
            _sockets[run_id].remove(ws)


async def _send(ws: WebSocket, msg: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(msg, default=str))


# ── Pipeline execution ─────────────────────────────────────────────────


async def _execute(run_id: str, req: RunRequest) -> None:
    run = _runs[run_id]
    try:
        run["status"] = "running"
        await _broadcast(run_id, {"type": "status", "status": "running"})

        repo_root = str(Path(req.repo).resolve())
        cfg_path = req.config_path
        if cfg_path is None:
            candidate = Path(repo_root) / "conveyor-belt.yaml"
            if candidate.exists():
                cfg_path = str(candidate)
        cfg = load_config(cfg_path)

        # Build changed-file context
        pr_title = pr_body = ""
        if req.pr:
            from conveyor_belt.integrations.git import changed_files_from_pr, get_pr_body

            changed = await changed_files_from_pr(repo_root, req.pr)
            pr_title, pr_body = await get_pr_body(repo_root, req.pr)
        elif req.diff:
            from conveyor_belt.integrations.git import changed_files_from_diff

            changed = await changed_files_from_diff(repo_root, req.diff)
        else:
            from conveyor_belt.integrations.git import changed_files_from_staged

            changed = await changed_files_from_staged(repo_root)

        ctx = StationContext(
            repo_root=repo_root,
            pr_number=req.pr,
            pr_title=pr_title,
            pr_body=pr_body,
            languages=cfg.project.languages,
            changed_files=changed,
        )
        await _broadcast(run_id, {
            "type": "context",
            "changed_files": len(changed),
            "languages": cfg.project.languages,
        })

        # Select stations
        all_st = _available_stations(cfg)
        stations = {k: v for k, v in all_st.items() if not req.stations or k in req.stations}

        if not stations:
            run["status"] = "complete"
            report = {"gate_passed": True, "policy": cfg.gate.policy, "results": []}
            run["report"] = report
            await _broadcast(run_id, {"type": "pipeline_complete", "report": report})
            return

        for name in stations:
            run["stations"][name] = {"status": "pending", "result": None}
        await _broadcast(run_id, {"type": "stations_init", "stations": list(stations.keys())})

        # Run stations in parallel, emitting events as each completes
        async def _run_one(name: str, station: Any) -> StationResult:
            run["stations"][name]["status"] = "running"
            await _broadcast(run_id, {"type": "station_start", "station": name})
            try:
                result = await station.execute(ctx)
            except Exception as exc:
                result = StationResult(station_name=name, passed=False, summary=str(exc))
            run["stations"][name]["status"] = "complete"
            serialised = result.model_dump()
            run["stations"][name]["result"] = serialised
            await _broadcast(run_id, {
                "type": "station_complete",
                "station": name,
                "result": serialised,
            })
            return result

        results: list[StationResult] = await asyncio.gather(
            *[_run_one(n, s) for n, s in stations.items()]
        )

        policy = cfg.gate.policy
        gate_passed = policy == "soft_fail" or all(r.passed for r in results)
        report = {
            "gate_passed": gate_passed,
            "policy": policy,
            "results": [r.model_dump() for r in results],
        }
        run["report"] = report
        run["status"] = "complete"
        await _broadcast(run_id, {"type": "pipeline_complete", "report": report})

    except Exception as exc:
        run["status"] = "error"
        run["error"] = str(exc)
        await _broadcast(run_id, {"type": "error", "message": str(exc)})
