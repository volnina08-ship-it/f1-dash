"""Markdown + PNG reports from backtest snapshots.

Two products:
- per-race report: win-probability time series (the CNN-election-night
  chart — also the demo/marketing asset) + final probability table;
- aggregate calibration report: metric tables vs baselines per phase and
  the reliability diagram.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (backend must be set first)

from apexodds.backtest.calibrate import CalibrationSummary  # noqa: E402

log = logging.getLogger(__name__)

TEAM_FALLBACK_CYCLE = (
    "#3671C6", "#FF8000", "#E80020", "#27F4D2", "#229971",
    "#64C4FF", "#0093CC", "#B6BABD", "#52E252", "#6692FF",
)


def race_report(snapshots: pd.DataFrame, out_dir: str | Path, top_n: int = 6) -> Path:
    """Write ``{session}.md`` + win-probability chart for one replayed race."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = str(snapshots["session_key"].iloc[0])

    chart_path = out_dir / f"{session}_win_prob.png"
    _win_prob_chart(snapshots, chart_path, top_n=top_n)

    final_lap = snapshots["lap"].max()
    final = snapshots[snapshots["lap"] == final_lap].sort_values("win_p", ascending=False)
    cols = ["code", "current_position", "win_p", "podium_p", "top10_p",
            "exp_finish", "actual_position"]
    cols = [c for c in cols if c in final.columns]

    md = [
        f"# Backtest report — {session}",
        "",
        f"Snapshots: laps 0-{final_lap}, {snapshots['driver_number'].nunique()} drivers.",
        "",
        f"![win probability]({chart_path.name})",
        "",
        f"## Probabilities at lap {final_lap}",
        "",
        final[cols].round(3).to_markdown(index=False),
        "",
    ]
    md_path = out_dir / f"{session}.md"
    md_path.write_text("\n".join(md))
    log.info("wrote %s", md_path)
    return md_path


def _win_prob_chart(snapshots: pd.DataFrame, path: Path, top_n: int = 6) -> None:
    pivot = snapshots.pivot_table(index="lap", columns="code", values="win_p")
    top = pivot.max().sort_values(ascending=False).head(top_n).index

    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=130)
    for code in pivot.columns:
        series = pivot[code]
        if code in top:
            color = TEAM_FALLBACK_CYCLE[list(top).index(code) % len(TEAM_FALLBACK_CYCLE)]
            ax.plot(series.index, series * 100, label=code, lw=2.0, color=color)
        else:
            ax.plot(series.index, series * 100, lw=0.7, color="#999999", alpha=0.5)

    if "track_status" in snapshots.columns:
        status = snapshots.groupby("lap")["track_status"].first()
        for lap, st in status.items():
            if st in ("SC", "VSC", "RED"):
                ax.axvspan(lap - 0.5, lap + 0.5, color="#f0c000", alpha=0.18, lw=0)

    ax.set_xlabel("Lap")
    ax.set_ylabel("Win probability (%)")
    ax.set_title(f"Win probability — {snapshots['session_key'].iloc[0]}")
    ax.set_ylim(0, 100)
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", ncols=2, frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def calibration_report(
    summary: CalibrationSummary, out_dir: str | Path, title: str = "Calibration report"
) -> Path:
    """Aggregate metrics + reliability diagram → markdown."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rel_path = out_dir / "reliability_win.png"
    _reliability_chart(summary, rel_path)

    md = [f"# {title}", ""]
    gate = "PASS" if summary.passes_phase0_gate() else "FAIL"
    md += [f"**Phase 0 gate (beat both baselines mid-race, ±5% calibration): {gate}**", ""]
    for target, g in summary.metrics.groupby("target"):
        md += [f"## {target}", ""]
        table = g.pivot_table(index="phase", columns="source", values="brier").round(4)
        md += ["Brier score (lower is better):", "", table.to_markdown(), ""]
        ll = g.pivot_table(index="phase", columns="source", values="log_loss").round(4)
        md += ["Log loss:", "", ll.to_markdown(), ""]
    md += ["## Reliability (win)", "", f"![reliability]({rel_path.name})", ""]

    path = out_dir / "calibration.md"
    path.write_text("\n".join(md))
    log.info("wrote %s", path)
    return path


def _reliability_chart(summary: CalibrationSummary, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(5.5, 5.5), dpi=130)
    ax.plot([0, 1], [0, 1], "--", color="#888888", lw=1, label="perfect")
    for target, table in summary.reliability.items():
        if table.empty:
            continue
        ax.plot(table["p_mean"], table["y_rate"], "o-", ms=4, lw=1.5, label=target)
    ax.set_xlabel("Predicted probability")
    ax.set_ylabel("Observed frequency")
    ax.set_title("Reliability")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
