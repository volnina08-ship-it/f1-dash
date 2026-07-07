"""Calibration metrics and naive baselines (Phase 0 success criteria).

Success gate (brief §7): between 30% and 70% race distance the engine must
beat BOTH naive baselines on Brier score, and the reliability curve must
stay within ±5 percentage points.

Baselines:
- ``leader``: "the current order holds" — the current leader wins with
  near-certainty (ε-smoothed so log loss stays finite).
- ``grid``:  static win probability by grid slot (historical prior),
  constant for the whole race.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

EPS = 1e-6

# P(win | grid position) prior, roughly matching the hybrid era; positions
# beyond the table get the tail value, then everything is renormalized per
# session. Replace with a fitted table from Jolpica data in M2.
DEFAULT_GRID_WIN_P = np.array(
    [0.40, 0.22, 0.12, 0.08, 0.05, 0.035, 0.025, 0.018, 0.012, 0.008,
     0.006, 0.005, 0.004, 0.003, 0.002, 0.002, 0.001, 0.001, 0.001, 0.001]
)

PHASES = ((0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01))
TARGETS = {"win": ("win_p", "actual_win"), "podium": ("podium_p", "actual_podium"),
           "top10": ("top10_p", "actual_top10")}


def brier_score(p: np.ndarray, y: np.ndarray) -> float:
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def reliability_table(p: np.ndarray, y: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Binned predicted-vs-observed frequencies (reliability diagram data)."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    rows = []
    for b in range(bins):
        sel = idx == b
        if not sel.any():
            continue
        rows.append(
            {
                "bin_low": edges[b],
                "bin_high": edges[b + 1],
                "p_mean": float(p[sel].mean()),
                "y_rate": float(y[sel].mean()),
                "count": int(sel.sum()),
            }
        )
    return pd.DataFrame(rows)


def expected_calibration_error(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    table = reliability_table(p, y, bins)
    if table.empty:
        return float("nan")
    w = table["count"] / table["count"].sum()
    return float((w * (table["p_mean"] - table["y_rate"]).abs()).sum())


def max_calibration_gap(p: np.ndarray, y: np.ndarray, bins: int = 10, min_count: int = 30) -> float:
    """Largest |predicted − observed| across well-populated bins — the
    '±5%' criterion checks this."""
    table = reliability_table(p, y, bins)
    table = table[table["count"] >= min_count]
    if table.empty:
        return float("nan")
    return float((table["p_mean"] - table["y_rate"]).abs().max())


# ------------------------------------------------------------------ baselines


def add_baselines(snapshots: pd.DataFrame) -> pd.DataFrame:
    """Attach per-row baseline win/podium/top10 probabilities.

    Uses only ``current_position`` / ``grid_position`` — information the
    naive strategies would have at the same moment.
    """
    df = snapshots.copy()
    for prefix, pos_col in (("leader", "current_position"), ("grid", "grid_position")):
        pos = pd.to_numeric(df[pos_col], errors="coerce").fillna(20).astype(int)
        n_field = df.groupby(["session_key", "lap"])["driver_number"].transform("count")
        if prefix == "leader":
            # Current order holds: P(win)=1 for P1, smoothed.
            for target, cutoff in (("win", 1), ("podium", 3), ("top10", 10)):
                hit = (pos <= cutoff).astype(float)
                smooth = 0.02
                df[f"baseline_leader_{target}_p"] = hit * (1 - smooth) + (1 - hit) * (
                    smooth * cutoff / (n_field - cutoff).clip(lower=1)
                )
        else:
            table = DEFAULT_GRID_WIN_P
            raw = table[np.clip(pos.to_numpy() - 1, 0, len(table) - 1)]
            df["_grid_raw"] = raw
            norm = df.groupby(["session_key", "lap"])["_grid_raw"].transform("sum")
            df["baseline_grid_win_p"] = df["_grid_raw"] / norm
            # Podium/top10 from the same prior: P ∝ min(1, k * win-prior mass).
            df["baseline_grid_podium_p"] = (df["baseline_grid_win_p"] * 3).clip(upper=0.98)
            df["baseline_grid_top10_p"] = np.clip(
                0.5 + (10.5 - pos) * 0.045, 0.05, 0.97
            )
            df = df.drop(columns=["_grid_raw"])
    return df


# ----------------------------------------------------------------- evaluation


@dataclass
class CalibrationSummary:
    metrics: pd.DataFrame  # tidy: target × phase × source × metric columns
    reliability: dict[str, pd.DataFrame]  # per target (model only, all phases)

    def passes_phase0_gate(self) -> bool:
        """Brief §7: beat both baselines on Brier in the 25-75% phases and
        keep the win-probability calibration gap within 5 points."""
        m = self.metrics
        mid = m[m["phase"].isin(["25-50%", "50-75%"])]
        ok = True
        for _, g in mid.groupby(["target", "phase"]):
            model = g.loc[g["source"] == "model", "brier"]
            base = g.loc[g["source"] != "model", "brier"]
            if len(model) and len(base):
                ok &= bool(model.iloc[0] < base.min())
        gap = self.reliability.get("win")
        if gap is not None and len(gap):
            counts = gap["count"] >= 30
            if counts.any():
                ok &= bool(
                    (gap.loc[counts, "p_mean"] - gap.loc[counts, "y_rate"]).abs().max()
                    <= 0.05
                )
        return ok


def _phase_label(lo: float, hi: float) -> str:
    return f"{int(lo * 100)}-{int(min(hi, 1.0) * 100)}%"


def evaluate_snapshots(snapshots: pd.DataFrame) -> CalibrationSummary:
    """Model vs baselines, per target and race phase."""
    df = add_baselines(snapshots)
    frac = df["lap"] / df["total_laps"].clip(lower=1)
    rows = []
    for target, (p_col, y_col) in TARGETS.items():
        sources = {
            "model": p_col,
            "leader": f"baseline_leader_{target}_p",
            "grid": f"baseline_grid_{target}_p",
        }
        for lo, hi in PHASES:
            sel = (frac >= lo) & (frac < hi)
            if not sel.any():
                continue
            y = df.loc[sel, y_col].to_numpy()
            for source, col in sources.items():
                if col not in df.columns:
                    continue
                p = df.loc[sel, col].to_numpy()
                rows.append(
                    {
                        "target": target,
                        "phase": _phase_label(lo, hi),
                        "source": source,
                        "n": int(sel.sum()),
                        "brier": brier_score(p, y),
                        "log_loss": log_loss(p, y),
                        "ece": expected_calibration_error(p, y),
                    }
                )
    reliability = {
        target: reliability_table(df[p_col].to_numpy(), df[y_col].to_numpy())
        for target, (p_col, y_col) in TARGETS.items()
    }
    return CalibrationSummary(metrics=pd.DataFrame(rows), reliability=reliability)
