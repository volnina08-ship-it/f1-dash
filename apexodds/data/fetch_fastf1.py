"""FastF1 historical ETL → normalized parquet tables.

FastF1 keeps its own raw HTTP cache (data/fastf1_cache/); on top of that we
write the *internal-schema* tables per session under
``data/normalized/{session_key}/`` — those are what models, backtests and
the DB loader consume.

Usage:
    python -m apexodds.data.fetch_fastf1 --season 2024
    python -m apexodds.data.fetch_fastf1 --season 2024 --rounds 1-10 --sessions R Q
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from apexodds.config import get_settings
from apexodds.data import normalize

log = logging.getLogger(__name__)


def _fastf1():
    """Deferred import: fastf1 is a heavy optional dependency (extra 'etl')."""
    try:
        import fastf1
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "fastf1 is not installed — install the ETL extra: uv sync --extra etl"
        ) from exc
    settings = get_settings()
    settings.fastf1_cache_dir.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(settings.fastf1_cache_dir))
    return fastf1


def dump_session(
    year: int, round_number: int, session_type: str = "R", out_dir: str | Path | None = None
) -> Path | None:
    """Load one session via FastF1 and write normalized parquet tables."""
    fastf1 = _fastf1()
    settings = get_settings()
    key = normalize.session_key(year, round_number, session_type)
    target = Path(out_dir) if out_dir else settings.normalized_dir
    target = target / key
    target.mkdir(parents=True, exist_ok=True)

    session = fastf1.get_session(year, round_number, session_type)
    session.load(laps=True, telemetry=False, weather=True, messages=True)

    laps = normalize.fastf1_laps(session.laps, key)
    laps.to_parquet(target / "laps.parquet", index=False)

    results = normalize.fastf1_results(session.results, key)
    results.to_parquet(target / "results.parquet", index=False)

    if session.weather_data is not None and len(session.weather_data):
        normalize.fastf1_weather(session.weather_data, key).to_parquet(
            target / "weather.parquet", index=False
        )
    rcm = getattr(session, "race_control_messages", None)
    if rcm is not None and len(rcm):
        normalize.fastf1_race_control(rcm, key).to_parquet(
            target / "race_control.parquet", index=False
        )

    stints = normalize.stints_from_laps(laps)
    if len(stints):
        stints.to_parquet(target / "stints.parquet", index=False)
    pitstops = normalize.estimate_pit_total_loss(laps)
    if len(pitstops):
        pitstops.to_parquet(target / "pitstops.parquet", index=False)

    meta = {
        "session_key": key,
        "year": year,
        "round": round_number,
        "session_type": session_type,
        "event_name": str(session.event.get("EventName", "")),
        "circuit": str(session.event.get("Location", "")),
        "country": str(session.event.get("Country", "")),
        "total_laps": int(session.total_laps or 0) if session_type == "R" else None,
        "date": str(session.date),
    }
    (target / "session.json").write_text(json.dumps(meta, indent=2))
    log.info("wrote %s (%d laps, %d drivers)", target, len(laps), len(results))
    return target


def dump_season(
    year: int,
    rounds: list[int] | None = None,
    session_types: tuple[str, ...] = ("R",),
    out_dir: str | Path | None = None,
) -> list[Path]:
    """Dump a whole season (default: races only). Skips events that fail
    to load (testing, cancelled) with a warning instead of aborting."""
    fastf1 = _fastf1()
    schedule = fastf1.get_event_schedule(year, include_testing=False)
    todo = rounds or [int(r) for r in schedule["RoundNumber"].tolist() if int(r) > 0]
    written = []
    for rnd in todo:
        for st in session_types:
            try:
                path = dump_session(year, rnd, st, out_dir=out_dir)
            except Exception as exc:  # noqa: BLE001 — batch ETL must survive bad events
                log.warning("skipping %s round %s %s: %s", year, rnd, st, exc)
                continue
            if path:
                written.append(path)
    return written


def _parse_rounds(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump FastF1 seasons to normalized parquet")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--rounds", default=None, help="e.g. 1-10 or 1,5,22 (default: all)")
    parser.add_argument(
        "--sessions", nargs="+", default=["R"], help="session types: R Q S SQ FP1..."
    )
    parser.add_argument("--out", default=None, help="output dir (default: data/normalized)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    dump_season(
        args.season,
        rounds=_parse_rounds(args.rounds),
        session_types=tuple(args.sessions),
        out_dir=args.out,
    )


if __name__ == "__main__":
    main()
