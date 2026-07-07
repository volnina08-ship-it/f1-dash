"""OpenF1 REST client (historical, free tier) + session dumper.

Free-tier limits: 3 requests/second AND 30 requests/minute — enforced
client-side with sliding windows, plus retry with backoff on 429/5xx
(honouring ``Retry-After``). Batch downloads should be cached locally
(``dump_session`` writes parquet under data/raw/openf1/) and never
re-fetched.

Real-time OpenF1 (paid MQTT) lives in live_client.py, not here.

Usage:
    python -m apexodds.data.fetch_openf1 --year 2024 --type Race
    python -m apexodds.data.fetch_openf1 --session-key 9558
"""

from __future__ import annotations

import argparse
import logging
import time
from collections import deque
from pathlib import Path

import httpx
import pandas as pd

from apexodds.config import get_settings

log = logging.getLogger(__name__)

# Endpoints worth dumping for every race session. car_data (3.7 Hz telemetry)
# is intentionally not in the default set — it's ~2 orders of magnitude
# bigger and only needed for micro-analyses; fetch it explicitly.
DEFAULT_ENDPOINTS = (
    "drivers",
    "laps",
    "intervals",
    "stints",
    "pit",
    "position",
    "race_control",
    "weather",
)


class RateLimiter:
    """Sliding-window limiter for N-per-second and M-per-minute caps."""

    def __init__(self, max_per_second: int = 3, max_per_minute: int = 30) -> None:
        self.max_per_second = max_per_second
        self.max_per_minute = max_per_minute
        self._second: deque[float] = deque()
        self._minute: deque[float] = deque()

    def acquire(self) -> None:
        while True:
            now = time.monotonic()
            while self._second and now - self._second[0] >= 1.0:
                self._second.popleft()
            while self._minute and now - self._minute[0] >= 60.0:
                self._minute.popleft()
            waits = []
            if len(self._second) >= self.max_per_second:
                waits.append(1.0 - (now - self._second[0]))
            if len(self._minute) >= self.max_per_minute:
                waits.append(60.0 - (now - self._minute[0]))
            if not waits:
                break
            time.sleep(max(max(waits), 0.01))
        stamp = time.monotonic()
        self._second.append(stamp)
        self._minute.append(stamp)


class OpenF1Client:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 5,
        limiter: RateLimiter | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.openf1_base_url).rstrip("/")
        self.max_retries = max_retries
        self.limiter = limiter or RateLimiter(
            settings.openf1_max_per_second, settings.openf1_max_per_minute
        )
        self._client = client or httpx.Client(timeout=timeout)

    def get(self, endpoint: str, **params) -> list[dict]:
        """GET /v1/{endpoint}?{params} with rate limiting and retries.

        OpenF1 filter operators go straight into the key, e.g.
        ``client.get("laps", session_key=9558, lap_number__gte=10)`` becomes
        ``lap_number>=10`` (double-underscore suffixes gte/lte/gt/lt).
        """
        query = {}
        ops = {"__gte": ">=", "__lte": "<=", "__gt": ">", "__lt": "<"}
        for k, v in params.items():
            if v is None:
                continue
            for suffix, op in ops.items():
                if k.endswith(suffix):
                    # httpx encodes these as key%3E%3D=value which OpenF1 accepts
                    query[k[: -len(suffix)] + op] = v
                    break
            else:
                query[k] = v

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        delay = 1.0
        for attempt in range(self.max_retries + 1):
            self.limiter.acquire()
            try:
                resp = self._client.get(url, params=query)
            except httpx.TransportError as exc:
                if attempt == self.max_retries:
                    raise
                log.warning("openf1 %s transport error (%s), retrying", endpoint, exc)
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                retry_after = float(resp.headers.get("retry-after", delay))
                log.warning(
                    "openf1 %s -> %s, sleeping %.1fs", endpoint, resp.status_code, retry_after
                )
                time.sleep(retry_after)
                delay = min(delay * 2, 30)
                continue
            resp.raise_for_status()
        raise RuntimeError("unreachable")

    def get_df(self, endpoint: str, **params) -> pd.DataFrame:
        return pd.DataFrame(self.get(endpoint, **params))

    # ------------------------------------------------------------- shortcuts

    def sessions(self, year: int | None = None, session_name: str | None = None) -> pd.DataFrame:
        return self.get_df("sessions", year=year, session_name=session_name)

    def dump_session(
        self,
        session_key: int,
        out_dir: str | Path | None = None,
        endpoints: tuple[str, ...] = DEFAULT_ENDPOINTS,
        skip_existing: bool = True,
    ) -> Path:
        """Dump one session's endpoints to parquet under data/raw/openf1/."""
        settings = get_settings()
        base = Path(out_dir) if out_dir else settings.raw_dir / "openf1"
        target = base / str(session_key)
        target.mkdir(parents=True, exist_ok=True)
        for endpoint in endpoints:
            path = target / f"{endpoint}.parquet"
            if skip_existing and path.exists():
                log.info("skip %s (exists)", path)
                continue
            df = self.get_df(endpoint, session_key=session_key)
            df.to_parquet(path, index=False)
            log.info("wrote %s (%d rows)", path, len(df))
        return target

    def dump_year(
        self,
        year: int,
        session_name: str = "Race",
        out_dir: str | Path | None = None,
    ) -> list[Path]:
        sessions = self.sessions(year=year, session_name=session_name)
        out = []
        for _, row in sessions.iterrows():
            log.info("dumping %s %s (%s)", year, row.get("location"), row["session_key"])
            out.append(self.dump_session(int(row["session_key"]), out_dir=out_dir))
        return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump OpenF1 historical data to parquet")
    parser.add_argument("--year", type=int, help="dump all sessions of a year")
    parser.add_argument("--type", default="Race", help="session_name filter (default: Race)")
    parser.add_argument("--session-key", type=int, help="dump a single session_key")
    parser.add_argument("--out", default=None, help="output dir (default: data/raw/openf1)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    client = OpenF1Client()
    if args.session_key:
        client.dump_session(args.session_key, out_dir=args.out)
    elif args.year:
        client.dump_year(args.year, session_name=args.type, out_dir=args.out)
    else:
        parser.error("need --year or --session-key")


if __name__ == "__main__":
    main()
