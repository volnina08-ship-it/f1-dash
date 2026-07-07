"""Normalize source-specific dataframes into the internal schema.

Internal tables (mirroring db/schema.sql, times in integer milliseconds):

- ``laps``:      session_key, driver_number, code, team, lap_number,
                 lap_time_ms, s1_ms, s2_ms, s3_ms, is_pit_in, is_pit_out,
                 compound, tyre_age, stint_id, track_status, position
- ``results``:   session_key, driver_number, code, team, grid_position,
                 finish_position, classified, dnf, laps, points
- ``stints``:    session_key, driver_number, stint_id, compound,
                 lap_start, lap_end, tyre_age_start
- ``pitstops``:  session_key, driver_number, lap, pit_duration_ms, total_loss_ms
- ``race_control``: session_key, lap, category, flag, message, driver_number
- ``weather``:   session_key, time_offset_s, air_temp, track_temp, humidity,
                 rainfall, wind_speed

FastF1 TrackStatus codes are kept verbatim in ``track_status``
('1' green, '2' yellow, '4' SC, '5' red, '6' VSC, '7' VSC ending);
composite codes like '24' mean multiple statuses during the lap.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

COMPOUND_MAP = {
    "SOFT": "SOFT",
    "SUPERSOFT": "SOFT",
    "ULTRASOFT": "SOFT",
    "HYPERSOFT": "SOFT",
    "MEDIUM": "MEDIUM",
    "HARD": "HARD",
    "INTERMEDIATE": "INTERMEDIATE",
    "WET": "WET",
    "UNKNOWN": "MEDIUM",
    "TEST_UNKNOWN": "MEDIUM",
    "": "MEDIUM",
}


def session_key(year: int, round_number: int, session_type: str) -> str:
    return f"{year}_{int(round_number):02d}_{session_type}"


def canon_compound(value: object) -> str:
    return COMPOUND_MAP.get(str(value or "").upper(), "MEDIUM")


def _col(df: pd.DataFrame, name: str, default: object = np.nan) -> pd.Series:
    """Column as a Series, or a default-filled Series when absent."""
    if name in df.columns:
        return df[name]
    return pd.Series(default, index=df.index)


def _td_to_ms(series: pd.Series) -> pd.Series:
    """Timedelta (or numeric seconds) → nullable integer milliseconds."""
    if pd.api.types.is_timedelta64_dtype(series):
        ms = series.dt.total_seconds() * 1000.0
    else:
        ms = pd.to_numeric(series, errors="coerce") * 1000.0
    return ms.round().astype("Int64")


# ------------------------------------------------------------------- FastF1


def fastf1_laps(laps: pd.DataFrame, key: str) -> pd.DataFrame:
    """FastF1 ``Session.laps`` → internal ``laps``."""
    out = pd.DataFrame(
        {
            "session_key": key,
            "driver_number": pd.to_numeric(laps["DriverNumber"], errors="coerce").astype(
                "Int64"
            ),
            "code": laps["Driver"].astype(str),
            "team": _col(laps, "Team", "").astype(str),
            "lap_number": laps["LapNumber"].astype(int),
            "lap_time_ms": _td_to_ms(laps["LapTime"]),
            "s1_ms": _td_to_ms(laps["Sector1Time"]),
            "s2_ms": _td_to_ms(laps["Sector2Time"]),
            "s3_ms": _td_to_ms(laps["Sector3Time"]),
            "is_pit_in": laps["PitInTime"].notna(),
            "is_pit_out": laps["PitOutTime"].notna(),
            "compound": laps["Compound"].map(canon_compound),
            "tyre_age": pd.to_numeric(laps["TyreLife"], errors="coerce").astype("Int64"),
            "stint_id": pd.to_numeric(laps["Stint"], errors="coerce").astype("Int64"),
            "track_status": laps["TrackStatus"].astype(str),
            "position": pd.to_numeric(_col(laps, "Position"), errors="coerce").astype("Int64"),
        }
    )
    return out.sort_values(["driver_number", "lap_number"]).reset_index(drop=True)


def fastf1_results(results: pd.DataFrame, key: str) -> pd.DataFrame:
    """FastF1 ``Session.results`` → internal ``results``."""
    status = _col(results, "Status", "").astype(str)
    classified = status.str.contains("Finished|\\+", regex=True, na=False)
    out = pd.DataFrame(
        {
            "session_key": key,
            "driver_number": pd.to_numeric(results["DriverNumber"], errors="coerce").astype(
                "Int64"
            ),
            "code": results["Abbreviation"].astype(str),
            "team": _col(results, "TeamName", "").astype(str),
            "grid_position": pd.to_numeric(_col(results, "GridPosition"), errors="coerce").astype(
                "Int64"
            ),
            "finish_position": pd.to_numeric(_col(results, "Position"), errors="coerce").astype(
                "Int64"
            ),
            "classified": classified,
            "dnf": ~classified,
            "laps": pd.to_numeric(_col(results, "Laps"), errors="coerce").astype("Int64"),
            "points": pd.to_numeric(_col(results, "Points"), errors="coerce").fillna(0.0),
        }
    )
    return out.reset_index(drop=True)


def fastf1_weather(weather: pd.DataFrame, key: str) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "session_key": key,
            "time_offset_s": weather["Time"].dt.total_seconds(),
            "air_temp": weather["AirTemp"].astype(float),
            "track_temp": weather["TrackTemp"].astype(float),
            "humidity": weather["Humidity"].astype(float),
            "rainfall": weather["Rainfall"].astype(bool),
            "wind_speed": pd.to_numeric(_col(weather, "WindSpeed"), errors="coerce"),
        }
    )
    return out.reset_index(drop=True)


def fastf1_race_control(messages: pd.DataFrame, key: str) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "session_key": key,
            "lap": pd.to_numeric(_col(messages, "Lap"), errors="coerce").astype("Int64"),
            "category": _col(messages, "Category", "").astype(str),
            "flag": _col(messages, "Flag", "").fillna("").astype(str),
            "message": _col(messages, "Message", "").astype(str),
            "driver_number": pd.to_numeric(_col(messages, "RacingNumber"), errors="coerce").astype(
                "Int64"
            ),
        }
    )
    return out.reset_index(drop=True)


# ------------------------------------------------------------------- OpenF1


def openf1_laps(
    laps: pd.DataFrame,
    key: str,
    stints: pd.DataFrame | None = None,
    drivers: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """OpenF1 ``laps`` (+``stints``, +``drivers``) → internal ``laps``.

    OpenF1 lap rows don't carry compound/stint; they're joined from the
    stints endpoint by lap range. ``is_pit_in`` is inferred: the lap before
    a pit-out lap is the in-lap.
    """
    df = laps.copy()
    out = pd.DataFrame(
        {
            "session_key": key,
            "driver_number": df["driver_number"].astype("Int64"),
            "code": "",
            "team": "",
            "lap_number": df["lap_number"].astype(int),
            "lap_time_ms": _td_to_ms(df["lap_duration"]),
            "s1_ms": _td_to_ms(_col(df, "duration_sector_1")),
            "s2_ms": _td_to_ms(_col(df, "duration_sector_2")),
            "s3_ms": _td_to_ms(_col(df, "duration_sector_3")),
            "is_pit_out": _col(df, "is_pit_out_lap", False),
            "track_status": "1",
            "position": pd.NA,
        }
    )
    out["is_pit_out"] = out["is_pit_out"].fillna(False).astype(bool)
    out = out.sort_values(["driver_number", "lap_number"]).reset_index(drop=True)
    nxt = out.groupby("driver_number")["is_pit_out"].shift(-1)
    out["is_pit_in"] = nxt.fillna(False).astype(bool)

    out["compound"] = "MEDIUM"
    out["tyre_age"] = pd.NA
    out["stint_id"] = pd.NA
    if stints is not None and len(stints):
        st = openf1_stints(stints, key)
        for row in st.itertuples():
            sel = (out["driver_number"] == row.driver_number) & out["lap_number"].between(
                row.lap_start, row.lap_end
            )
            out.loc[sel, "compound"] = row.compound
            out.loc[sel, "stint_id"] = row.stint_id
            out.loc[sel, "tyre_age"] = (
                out.loc[sel, "lap_number"] - row.lap_start + row.tyre_age_start
            )
    if drivers is not None and len(drivers):
        meta = drivers.set_index("driver_number")
        out["code"] = out["driver_number"].map(meta.get("name_acronym", pd.Series()).to_dict())
        out["team"] = out["driver_number"].map(meta.get("team_name", pd.Series()).to_dict())
    out["tyre_age"] = out["tyre_age"].astype("Int64")
    out["stint_id"] = out["stint_id"].astype("Int64")
    return out[
        [
            "session_key", "driver_number", "code", "team", "lap_number",
            "lap_time_ms", "s1_ms", "s2_ms", "s3_ms", "is_pit_in", "is_pit_out",
            "compound", "tyre_age", "stint_id", "track_status", "position",
        ]
    ]


def openf1_stints(stints: pd.DataFrame, key: str) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "session_key": key,
            "driver_number": stints["driver_number"].astype("Int64"),
            "stint_id": stints["stint_number"].astype(int),
            "compound": stints["compound"].map(canon_compound),
            "lap_start": stints["lap_start"].astype(int),
            "lap_end": stints["lap_end"].astype(int),
            "tyre_age_start": pd.to_numeric(_col(stints, "tyre_age_at_start", 0), errors="coerce")
            .fillna(0)
            .astype(int),
        }
    )
    return out.sort_values(["driver_number", "stint_id"]).reset_index(drop=True)


def openf1_race_control(rc: pd.DataFrame, key: str) -> pd.DataFrame:
    out = pd.DataFrame(
        {
            "session_key": key,
            "lap": pd.to_numeric(_col(rc, "lap_number"), errors="coerce").astype("Int64"),
            "category": _col(rc, "category", "").astype(str),
            "flag": _col(rc, "flag", "").fillna("").astype(str),
            "message": _col(rc, "message", "").astype(str),
            "driver_number": pd.to_numeric(_col(rc, "driver_number"), errors="coerce").astype(
                "Int64"
            ),
        }
    )
    return out.reset_index(drop=True)


# ------------------------------------------------------- derived quantities


def stints_from_laps(laps: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the ``stints`` table from a normalized ``laps`` table."""
    rows = []
    for (driver, stint_id), g in laps.dropna(subset=["stint_id"]).groupby(
        ["driver_number", "stint_id"]
    ):
        ages = g["tyre_age"].dropna()
        start_age = int(ages.iloc[0]) - 1 if len(ages) else 0
        rows.append(
            {
                "session_key": g["session_key"].iloc[0],
                "driver_number": driver,
                "stint_id": int(stint_id),
                "compound": g["compound"].iloc[0],
                "lap_start": int(g["lap_number"].min()),
                "lap_end": int(g["lap_number"].max()),
                "tyre_age_start": max(start_age, 0),
            }
        )
    return pd.DataFrame(rows)


def estimate_pit_total_loss(laps: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Per-stop *total* time loss from a normalized ``laps`` table.

    total_loss ≈ (in-lap + out-lap) − 2 × the driver's reference pace, where
    the reference is the median clean lap within ``window`` racing laps on
    either side of the stop. Green-flag stops only (interventions distort
    the reference); rows with too little context are dropped.
    """
    from apexodds.models.pace import clean_lap_mask

    laps = laps.sort_values(["driver_number", "lap_number"])
    rows = []
    for driver, g in laps.groupby("driver_number"):
        g = g.reset_index(drop=True)
        gc = clean_lap_mask(g)
        in_laps = g.index[g["is_pit_in"].fillna(False).astype(bool)]
        for i in in_laps:
            lap_no = int(g.loc[i, "lap_number"])
            out_i = i + 1
            if out_i not in g.index:
                continue
            status = str(g.loc[i, "track_status"])
            if status not in ("", "1"):
                continue  # intervention stop → cheap, not representative
            near = g[
                gc
                & (g["lap_number"] >= lap_no - window)
                & (g["lap_number"] <= lap_no + window + 1)
            ]["lap_time_ms"].dropna()
            if len(near) < 2:
                continue
            in_ms = g.loc[i, "lap_time_ms"]
            out_ms = g.loc[out_i, "lap_time_ms"]
            if pd.isna(in_ms) or pd.isna(out_ms):
                continue
            ref = float(near.median())
            loss = float(in_ms) + float(out_ms) - 2.0 * ref
            if loss <= 0 or loss > 90_000:
                continue
            rows.append(
                {
                    "session_key": g.loc[i, "session_key"],
                    "driver_number": driver,
                    "lap": lap_no,
                    "pit_duration_ms": pd.NA,
                    "total_loss_ms": int(round(loss)),
                }
            )
    return pd.DataFrame(rows)
