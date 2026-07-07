"use client";

import { useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { MAX_LAP, RACE, useReplay } from "@/lib/replay";
import { fmtPct } from "@/lib/format";

const W = 760;
const H = 300;
const M = { l: 10, r: 64, t: 12, b: 22 };

const x = (lap: number) => M.l + (lap / MAX_LAP) * (W - M.l - M.r);
const y = (p: number) => M.t + (1 - p) * (H - M.t - M.b);

/** Drivers worth a highlighted line: top 6 by peak win probability. */
const HIGHLIGHT = [...RACE.drivers]
  .map((d) => ({
    d,
    peak: Math.max(...RACE.laps.map((l) => l.p[String(d.num)]?.win ?? 0)),
  }))
  .sort((a, b) => b.peak - a.peak)
  .slice(0, 6)
  .map(({ d }) => d);

const HIGHLIGHT_NUMS = new Set(HIGHLIGHT.map((d) => d.num));

// Teammates in the highlight set share a color → second one gets a dash.
const DASHED = new Set<number>();
{
  const seen = new Set<string>();
  for (const d of HIGHLIGHT) {
    if (seen.has(d.team)) DASHED.add(d.num);
    seen.add(d.team);
  }
}

function pathFor(num: number, upto: number): string {
  const pts: string[] = [];
  for (let l = 0; l <= upto; l++) {
    const p = RACE.laps[l].p[String(num)]?.win ?? 0;
    pts.push(`${l ? "L" : "M"}${x(l).toFixed(1)},${y(p).toFixed(1)}`);
  }
  return pts.join("");
}

/** SC/VSC bands for context. */
const BANDS: { from: number; to: number; kind: string }[] = (() => {
  const out: { from: number; to: number; kind: string }[] = [];
  let open: { from: number; kind: string } | null = null;
  RACE.laps.forEach((l) => {
    const kind = l.status === "SC" || l.status === "VSC" ? l.status : null;
    if (kind && !open) open = { from: l.lap, kind };
    if (open && (!kind || kind !== open.kind)) {
      out.push({ from: open.from, to: l.lap, kind: open.kind });
      open = kind ? { from: l.lap, kind } : null;
    }
  });
  return out;
})();

export default function WinChart() {
  const { lap, seek } = useReplay();
  const [hoverLap, setHoverLap] = useState<number | null>(null);
  const [focus, setFocus] = useState<number | null>(null); // driver num via legend
  const box = useRef<HTMLDivElement>(null);

  const current = RACE.laps[lap];

  // End-of-line labels: current values of highlighted drivers, de-collided.
  const endLabels = useMemo(() => {
    const items = HIGHLIGHT.map((d) => ({
      d,
      v: current.p[String(d.num)]?.win ?? 0,
    }))
      .filter((it) => it.v > 0.004)
      .sort((a, b) => y(a.v) - y(b.v))
      .map((it) => ({ ...it, ly: y(it.v) }));
    // De-collide downwards, then clamp the cluster back inside the plot.
    for (let i = 1; i < items.length; i++) {
      if (items[i].ly - items[i - 1].ly < 15) items[i].ly = items[i - 1].ly + 15;
    }
    const floor = H - M.b - 4;
    for (let i = items.length - 1; i >= 0; i--) {
      const maxY = floor - (items.length - 1 - i) * 15;
      if (items[i].ly > maxY) items[i].ly = maxY;
    }
    return items;
  }, [current]);

  const hover = hoverLap !== null ? RACE.laps[hoverLap] : null;
  const hoverRows = hover
    ? HIGHLIGHT.map((d) => ({ d, v: hover.p[String(d.num)]?.win ?? 0 }))
        .sort((a, b) => b.v - a.v)
        .slice(0, 6)
    : [];

  const toLap = (clientX: number) => {
    const rect = box.current!.getBoundingClientRect();
    const relX = ((clientX - rect.left) / rect.width) * W;
    return Math.max(0, Math.min(MAX_LAP, Math.round(((relX - M.l) / (W - M.l - M.r)) * MAX_LAP)));
  };

  return (
    <section className="glass rounded-2xl p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-[13px] font-bold uppercase tracking-[0.2em]">
            Win probability
          </h2>
          <p className="num mt-0.5 text-[10px] text-[--color-ink-3]">
            P(win) per driver · recomputed every lap from {RACE.session.nSims.toLocaleString()} simulated race endings
          </p>
        </div>
      </div>

      {/* legend — fixed entity colors, hover to isolate */}
      <div className="mb-2 flex flex-wrap gap-1.5">
        {HIGHLIGHT.map((d) => (
          <button
            key={d.num}
            onMouseEnter={() => setFocus(d.num)}
            onMouseLeave={() => setFocus(null)}
            className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/4 px-2 py-[3px] text-[10px] font-semibold transition-colors hover:bg-white/10"
          >
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: d.color, boxShadow: `0 0 6px ${d.color}` }}
            />
            {d.code}
            <span className="num text-[--color-ink-3]">
              {fmtPct(current.p[String(d.num)]?.win ?? 0)}
            </span>
          </button>
        ))}
      </div>

      <div
        ref={box}
        className="relative cursor-crosshair select-none"
        onMouseMove={(e) => setHoverLap(toLap(e.clientX))}
        onMouseLeave={() => setHoverLap(null)}
        onClick={(e) => seek(toLap(e.clientX))}
      >
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
          {/* grid */}
          {[0.25, 0.5, 0.75, 1].map((g) => (
            <g key={g}>
              <line
                x1={M.l}
                x2={W - M.r}
                y1={y(g)}
                y2={y(g)}
                stroke="rgba(255,255,255,0.06)"
                strokeDasharray={g === 1 ? undefined : "3 5"}
              />
              <text
                x={W - M.r + 6}
                y={y(g) + 3}
                fill="rgba(255,255,255,0.28)"
                fontSize="9"
                fontFamily="var(--font-mono)"
              >
                {g * 100}
              </text>
            </g>
          ))}
          <line
            x1={M.l}
            x2={W - M.r}
            y1={y(0)}
            y2={y(0)}
            stroke="rgba(255,255,255,0.12)"
          />
          {/* lap axis ticks */}
          {[0, 10, 20, 30, 40, 50, 60, 70].map((l) => (
            <text
              key={l}
              x={x(l)}
              y={H - 6}
              textAnchor="middle"
              fill="rgba(255,255,255,0.28)"
              fontSize="9"
              fontFamily="var(--font-mono)"
            >
              {l}
            </text>
          ))}

          {/* SC / VSC bands */}
          {BANDS.map((b, i) => (
            <g key={i}>
              <rect
                x={x(b.from)}
                y={M.t}
                width={x(b.to) - x(b.from)}
                height={H - M.t - M.b}
                fill={b.kind === "SC" ? "rgba(255,194,51,0.08)" : "rgba(255,161,75,0.07)"}
              />
              <text
                x={(x(b.from) + x(b.to)) / 2}
                y={M.t + 10}
                textAnchor="middle"
                fill={b.kind === "SC" ? "rgba(255,194,51,0.7)" : "rgba(255,161,75,0.7)"}
                fontSize="8.5"
                fontFamily="var(--font-mono)"
                fontWeight="700"
              >
                {b.kind}
              </text>
            </g>
          ))}

          {/* background field lines */}
          {RACE.drivers
            .filter((d) => !HIGHLIGHT_NUMS.has(d.num))
            .map((d) => (
              <path
                key={d.num}
                d={pathFor(d.num, lap)}
                fill="none"
                stroke="rgba(255,255,255,0.10)"
                strokeWidth="1"
              />
            ))}

          {/* highlighted lines */}
          {HIGHLIGHT.map((d) => (
            <path
              key={d.num}
              d={pathFor(d.num, lap)}
              fill="none"
              stroke={d.color}
              strokeWidth={focus === d.num ? 3 : 2}
              strokeLinejoin="round"
              strokeLinecap="round"
              strokeDasharray={DASHED.has(d.num) ? "6 4" : undefined}
              pathLength={1}
              className="draw-in"
              opacity={focus && focus !== d.num ? 0.18 : 1}
              style={{
                filter:
                  focus === d.num
                    ? `drop-shadow(0 0 6px ${d.color})`
                    : "drop-shadow(0 1px 4px rgba(0,0,0,0.5))",
                transition: "opacity 0.25s ease",
              }}
            />
          ))}

          {/* hover crosshair */}
          {hoverLap !== null && (
            <line
              x1={x(hoverLap)}
              x2={x(hoverLap)}
              y1={M.t}
              y2={H - M.b}
              stroke="rgba(255,255,255,0.30)"
              strokeDasharray="3 4"
            />
          )}

          {/* playhead */}
          <motion.g
            animate={{ x: x(lap) - x(0) }}
            transition={{ type: "tween", duration: 0.45, ease: "easeOut" }}
          >
            <line
              x1={x(0)}
              x2={x(0)}
              y1={M.t - 2}
              y2={H - M.b}
              stroke="#ff2438"
              strokeWidth="1.5"
              style={{ filter: "drop-shadow(0 0 5px rgba(255,36,56,0.9))" }}
            />
            <path
              d={`M${x(0) - 4},${M.t - 2} L${x(0) + 4},${M.t - 2} L${x(0)},${M.t + 5} Z`}
              fill="#ff2438"
            />
          </motion.g>

          {/* current-value dots + end labels */}
          {endLabels.map(({ d, v, ly }) => (
            <g key={d.num} opacity={focus && focus !== d.num ? 0.2 : 1}>
              <circle
                cx={x(lap)}
                cy={y(v)}
                r="3.5"
                fill={d.color}
                stroke="#0b0a10"
                strokeWidth="1.5"
              />
              <text
                x={x(lap) + 8}
                y={ly + 3}
                fontSize="10"
                fontWeight="700"
                fontFamily="var(--font-mono)"
                fill={d.color}
              >
                {d.code} {Math.round(v * 100)}
              </text>
            </g>
          ))}
        </svg>

        {/* hover tooltip */}
        {hover && hoverLap !== null && (
          <div
            className="glass-strong pointer-events-none absolute z-10 min-w-[130px] rounded-xl px-3 py-2"
            style={{
              left: `${(x(hoverLap) / W) * 100}%`,
              top: 8,
              transform: `translateX(${hoverLap > MAX_LAP * 0.7 ? "-108%" : "10px"})`,
            }}
          >
            <div className="num mb-1 text-[10px] font-bold text-[--color-ink-2]">
              LAP {hoverLap}
              {hover.status !== "GREEN" && (
                <span className="ml-1.5 text-[--color-flag-sc]">{hover.status}</span>
              )}
            </div>
            {hoverRows.map(({ d, v }) => (
              <div key={d.num} className="flex items-center gap-2 py-[1.5px]">
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: d.color }} />
                <span className="text-[10.5px] font-semibold">{d.code}</span>
                <span className="num ml-auto text-[10.5px] text-[--color-ink-2]">
                  {fmtPct(v)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
