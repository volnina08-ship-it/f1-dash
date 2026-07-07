"""Pydantic wire schemas for the dashboard API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DriverSnapshot(BaseModel):
    """One driver's probability row at one recalculation (leaderboard row)."""

    driver_number: int
    code: str
    team: str = ""
    current_position: int | None = None
    win_p: float = Field(ge=0.0, le=1.0)
    podium_p: float = Field(ge=0.0, le=1.0)
    top10_p: float = Field(ge=0.0, le=1.0)
    dnf_p: float = Field(ge=0.0, le=1.0)
    exp_finish: float
    finish_p5: int
    finish_p50: int
    finish_p95: int
    exp_points: float
    pit_prob: float = Field(ge=0.0, le=1.0)
    pit_window_open: int
    pit_window_p50: int
    pit_window_close: int


class LapSnapshot(BaseModel):
    """Everything the UI needs after one recalculation (one lap)."""

    session_key: str
    lap: int
    total_laps: int
    track_status: str = "GREEN"
    drivers: list[DriverSnapshot]


class SessionInfo(BaseModel):
    session_key: str
    laps_available: int
    total_laps: int
    drivers: list[str]


class ReplayControl(BaseModel):
    """Client → server message on the replay WebSocket."""

    action: str = "play"  # play | pause | seek
    lap: int | None = None
    speed: float = 1.0  # laps per second while playing
