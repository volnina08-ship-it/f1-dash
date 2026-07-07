"""API skeleton: REST + WebSocket replay against a snapshots fixture."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import apexodds.config as config
from apexodds.api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APEXODDS_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()

    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir(parents=True)
    rows = []
    for lap in (0, 1, 2):
        for i in range(3):
            rows.append(
                {
                    "session_key": "2024_99_R",
                    "lap": lap,
                    "total_laps": 50,
                    "driver_number": i + 1,
                    "code": f"D{i + 1:02d}",
                    "team": "T0",
                    "current_position": i + 1,
                    "win_p": [0.7, 0.2, 0.1][i],
                    "podium_p": 0.9,
                    "top10_p": 1.0,
                    "dnf_p": 0.05,
                    "exp_finish": float(i + 1),
                    "finish_p5": 1,
                    "finish_p50": i + 1,
                    "finish_p95": 3,
                    "exp_points": 10.0,
                    "pit_prob": 0.9,
                    "pit_window_open": 18,
                    "pit_window_p50": 22,
                    "pit_window_close": 26,
                    "track_status": "GREEN",
                }
            )
    pd.DataFrame(rows).to_parquet(snap_dir / "2024_99_R.parquet", index=False)

    with TestClient(app) as c:
        yield c
    config.get_settings.cache_clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_sessions_lists_replayable_races(client):
    body = client.get("/sessions").json()
    assert len(body) == 1
    assert body[0]["session_key"] == "2024_99_R"
    assert body[0]["laps_available"] == 3
    assert body[0]["drivers"] == ["D01", "D02", "D03"]


def test_snapshot_at_lap(client):
    body = client.get("/snapshots/2024_99_R/1").json()
    assert body["lap"] == 1
    assert body["total_laps"] == 50
    assert [d["code"] for d in body["drivers"]] == ["D01", "D02", "D03"]
    assert body["drivers"][0]["win_p"] == pytest.approx(0.7)


def test_snapshot_series_filter(client):
    body = client.get("/snapshots/2024_99_R", params={"driver": "d02"}).json()
    assert len(body) == 3
    assert {row["code"] for row in body} == {"D02"}


def test_missing_session_404(client):
    assert client.get("/snapshots/nope/1").status_code == 404


def test_websocket_replay_stream(client):
    with client.websocket_connect("/ws/replay/2024_99_R?speed=50") as ws:
        seen = []
        while True:
            msg = ws.receive_json()
            if msg.get("event") == "replay_end":
                break
            seen.append(msg["lap"])
            assert len(msg["drivers"]) == 3
            assert np.isclose(sum(d["win_p"] for d in msg["drivers"]), 1.0)
    assert seen == [0, 1, 2]
