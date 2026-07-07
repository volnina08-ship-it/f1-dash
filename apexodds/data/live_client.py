"""Live data sources (Phase 1) + a functional replay source.

Interface: an async iterator of ``LiveMessage``s. Three implementations:

- :class:`ReplayLiveSource` — **works today**: replays a normalized session
  from parquet lap by lap with wall-clock pacing. This powers development,
  demos and the Phase 1 replay mode without any live subscription.
- :class:`OpenF1LiveSource` — primary live source, OpenF1 paid real-time
  (MQTT over WebSocket, ~3 s latency). Stub until the subscription exists.
- :class:`SignalRLiveSource` — backup source via the ``livef1`` package
  (F1's official SignalR live timing stream). Stub.

Both live feeds are unofficial; Phase 0-1 usage is non-commercial (see
brief §2.2/§10 — commercial licensing before any B2B step).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


@dataclass(frozen=True)
class LiveMessage:
    """One update from a live (or replayed) session."""

    topic: str  # e.g. "laps", "race_control", "session_end"
    session_key: str
    lap: int | None
    payload: Any  # topic-specific: list[dict] rows, dict meta, ...


class LiveSource(Protocol):
    def stream(self) -> AsyncIterator[LiveMessage]: ...


@dataclass
class ReplayLiveSource:
    """Replay a normalized session directory as if it were live.

    Emits one ``laps`` message per race lap (all rows of that lap) plus
    ``race_control`` messages attached to the lap, then ``session_end``.
    ``lap_interval_s`` is the wall-clock pause per lap (0 for tests /
    as-fast-as-possible backtests; ~90/speed for realistic demos).
    """

    session_dir: str | Path
    lap_interval_s: float = 0.0
    _meta: dict = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.session_dir = Path(self.session_dir)
        meta_path = self.session_dir / "session.json"
        self._meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    @property
    def session_key(self) -> str:
        return self._meta.get("session_key", self.session_dir.name)

    async def stream(self) -> AsyncIterator[LiveMessage]:
        laps = pd.read_parquet(self.session_dir / "laps.parquet")
        rc_path = self.session_dir / "race_control.parquet"
        rc = pd.read_parquet(rc_path) if rc_path.exists() else pd.DataFrame()
        key = self.session_key

        for lap in sorted(laps["lap_number"].unique()):
            lap_rows = laps[laps["lap_number"] == lap]
            yield LiveMessage(
                topic="laps",
                session_key=key,
                lap=int(lap),
                payload=lap_rows.to_dict(orient="records"),
            )
            if len(rc) and "lap" in rc.columns:
                rc_rows = rc[rc["lap"] == lap]
                if len(rc_rows):
                    yield LiveMessage(
                        topic="race_control",
                        session_key=key,
                        lap=int(lap),
                        payload=rc_rows.to_dict(orient="records"),
                    )
            if self.lap_interval_s > 0:
                await asyncio.sleep(self.lap_interval_s)
        yield LiveMessage(topic="session_end", session_key=key, lap=None, payload=self._meta)


@dataclass
class OpenF1LiveSource:
    """OpenF1 paid real-time feed (MQTT over WebSocket). Phase 1.

    TODO(phase1): implement with paho-mqtt against the OpenF1 realtime
    broker once the subscription is active; map topics (laps, intervals,
    position, race_control, weather) into LiveMessage batches keyed by lap.
    """

    api_key: str = ""

    async def stream(self) -> AsyncIterator[LiveMessage]:
        raise NotImplementedError(
            "OpenF1 real-time needs the paid MQTT subscription (Phase 1 / M6)."
        )
        yield  # pragma: no cover — makes this an async generator


@dataclass
class SignalRLiveSource:
    """Backup: F1 official SignalR live timing via the `livef1` package.

    TODO(phase1): subscribe to TimingData / CarData.z / Position.z topics
    with livef1's async client and adapt its callbacks into LiveMessages.
    """

    topics: tuple[str, ...] = ("TimingData", "TimingAppData", "RaceControlMessages")

    async def stream(self) -> AsyncIterator[LiveMessage]:
        raise NotImplementedError("SignalR backup source is a Phase 1 task (extra 'live').")
        yield  # pragma: no cover — makes this an async generator
