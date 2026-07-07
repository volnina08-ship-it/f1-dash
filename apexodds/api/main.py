"""FastAPI service: snapshot REST + WebSocket replay stream.

Phase 1a scope: serve backtest-produced ``sim_snapshots`` parquet files
(data/snapshots/{session_key}.parquet) so the web dashboard can replay any
backtested race as if it were live — the demo mode from the brief (§8).
The live path (M6) will push freshly computed snapshots through the same
WebSocket message shape.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from apexodds.api.schemas import DriverSnapshot, LapSnapshot, SessionInfo
from apexodds.config import get_settings

log = logging.getLogger(__name__)

app = FastAPI(
    title="APEXODDS API",
    version="0.1.0",
    description="Live F1 probability engine — replay-mode API (Phase 1 skeleton). "
    "Unofficial; not associated with Formula 1.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before any public deploy
    allow_methods=["*"],
    allow_headers=["*"],
)

DRIVER_COLS = [f.strip() for f in DriverSnapshot.model_fields]


def _snapshot_path(session_key: str) -> Path:
    return get_settings().snapshots_dir / f"{session_key}.parquet"


def _load_snapshots(session_key: str) -> pd.DataFrame:
    path = _snapshot_path(session_key)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"no snapshots for {session_key}")
    return pd.read_parquet(path)


def _lap_snapshot(df: pd.DataFrame, session_key: str, lap: int) -> LapSnapshot:
    rows = df[df["lap"] == lap]
    if rows.empty:
        raise HTTPException(status_code=404, detail=f"lap {lap} not in snapshots")
    drivers = [
        DriverSnapshot(**{k: row[k] for k in DRIVER_COLS if k in rows.columns})
        for _, row in rows.iterrows()
    ]
    drivers.sort(key=lambda d: d.current_position or 99)
    status = str(rows["track_status"].iloc[0]) if "track_status" in rows.columns else "GREEN"
    return LapSnapshot(
        session_key=session_key,
        lap=int(lap),
        total_laps=int(rows["total_laps"].iloc[0]),
        track_status=status,
        drivers=drivers,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/sessions", response_model=list[SessionInfo])
def sessions() -> list[SessionInfo]:
    """Replayable sessions (any backtested race)."""
    out = []
    directory = get_settings().snapshots_dir
    if directory.exists():
        for path in sorted(directory.glob("*.parquet")):
            df = pd.read_parquet(path, columns=["lap", "total_laps", "code"])
            out.append(
                SessionInfo(
                    session_key=path.stem,
                    laps_available=int(df["lap"].nunique()),
                    total_laps=int(df["total_laps"].iloc[0]),
                    drivers=sorted(df["code"].dropna().unique().tolist()),
                )
            )
    return out


@app.get("/snapshots/{session_key}/{lap}", response_model=LapSnapshot)
def snapshot_at(session_key: str, lap: int) -> LapSnapshot:
    return _lap_snapshot(_load_snapshots(session_key), session_key, lap)


@app.get("/snapshots/{session_key}")
def snapshot_series(session_key: str, driver: str | None = None) -> list[dict]:
    """Full probability time series (win-prob chart data)."""
    df = _load_snapshots(session_key)
    cols = ["lap", "driver_number", "code", "win_p", "podium_p", "top10_p", "exp_finish"]
    cols = [c for c in cols if c in df.columns]
    if driver:
        df = df[df["code"] == driver.upper()]
    return df[cols].to_dict(orient="records")


@app.websocket("/ws/replay/{session_key}")
async def replay_ws(ws: WebSocket, session_key: str, speed: float = 1.0) -> None:
    """Stream a backtested race lap by lap (``speed`` = laps per second).

    Phase 1 live mode will reuse this message shape, pushing snapshots as
    they are computed instead of on a timer.
    """
    await ws.accept()
    try:
        df = _load_snapshots(session_key)
    except HTTPException as exc:
        await ws.send_json({"error": exc.detail})
        await ws.close()
        return

    delay = 1.0 / max(speed, 0.05)
    try:
        for lap in sorted(df["lap"].unique()):
            payload = _lap_snapshot(df, session_key, int(lap))
            await ws.send_json(payload.model_dump())
            await asyncio.sleep(delay)
        await ws.send_json({"session_key": session_key, "event": "replay_end"})
        await ws.close()
    except WebSocketDisconnect:
        log.info("replay client disconnected (%s)", session_key)
