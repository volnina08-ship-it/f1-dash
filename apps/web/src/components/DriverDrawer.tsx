"use client";

import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { MAX_LAP, RACE, useReplay, useTweened } from "@/lib/replay";
import { fmtPct } from "@/lib/format";
import type { DriverMeta } from "@/lib/types";

/** 270° arc gauge for a probability. */
function Gauge({ value, label, color }: { value: number; label: string; color: string }) {
  const shown = useTweened(value);
  const R = 26;
  const C = 2 * Math.PI * R;
  const frac = 0.75 * Math.max(0, Math.min(1, shown));
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative h-[72px] w-[72px]">
        <svg viewBox="0 0 72 72" className="h-full w-full -rotate-[135deg]">
          <circle
            cx="36" cy="36" r={R} fill="none"
            stroke="rgba(255,255,255,0.08)" strokeWidth="6"
            strokeDasharray={`${C * 0.75} ${C}`} strokeLinecap="round"
          />
          <circle
            cx="36" cy="36" r={R} fill="none"
            stroke={color} strokeWidth="6"
            strokeDasharray={`${C * frac} ${C}`} strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 6px ${color}88)`, transition: "stroke-dasharray 0.15s linear" }}
          />
        </svg>
        <div className="num absolute inset-0 grid place-items-center pt-1 text-[13px] font-bold">
          {fmtPct(shown)}
        </div>
      </div>
      <span className="text-[9px] font-semibold uppercase tracking-[0.2em] text-[--color-ink-3]">
        {label}
      </span>
    </div>
  );
}

/** Finish-position distribution histogram (animated). */
function Histogram({ dist }: { dist: number[] }) {
  const max = Math.max(...dist, 0.01);
  return (
    <div>
      <div className="flex h-[86px] items-end gap-[3px]">
        {dist.map((p, i) => (
          <div key={i} className="group relative flex-1">
            <motion.div
              animate={{ height: `${(p / max) * 82 + (p > 0 ? 3 : 1)}px` }}
              transition={{ type: "spring", stiffness: 260, damping: 28 }}
              className="w-full rounded-t-[3px]"
              style={{
                background:
                  i === 0
                    ? "linear-gradient(180deg,#ff5c68,#ff2438)"
                    : i < 3
                      ? "rgba(255,92,104,0.55)"
                      : i < 10
                        ? "rgba(255,255,255,0.30)"
                        : "rgba(255,255,255,0.10)",
                boxShadow: i === 0 && p > 0.05 ? "0 0 10px rgba(255,36,56,0.5)" : undefined,
              }}
              title={`P${i + 1}: ${fmtPct(p, 1)}`}
            />
          </div>
        ))}
      </div>
      <div className="num mt-1 flex justify-between text-[8.5px] text-[--color-ink-3]">
        <span>P1</span><span>P5</span><span>P10</span><span>P15</span><span>P20</span>
      </div>
    </div>
  );
}

/** Predicted next-stop window on a lap axis. */
function PitWindow({ num }: { num: number }) {
  const { lap } = useReplay();
  const p = RACE.laps[lap].p[String(num)];
  if (!p) return null;
  if (p.pitP < 0.35 || p.pitMid === 0) {
    return (
      <p className="num text-[10.5px] text-[--color-ink-3]">
        No further stop expected — P(stop) {fmtPct(p.pitP)}
      </p>
    );
  }
  const px = (l: number) => `${(l / MAX_LAP) * 100}%`;
  return (
    <div>
      <div className="relative h-[26px]">
        <div className="absolute inset-x-0 top-1/2 h-[4px] -translate-y-1/2 rounded-full bg-white/8" />
        <div
          className="absolute top-1/2 h-[10px] -translate-y-1/2 rounded-full bg-[--color-accent]/25 border border-[--color-accent]/40"
          style={{ left: px(p.pitLo), width: `calc(${px(p.pitHi)} - ${px(p.pitLo)})` }}
        />
        <div
          className="absolute top-1/2 h-[14px] w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[--color-accent]"
          style={{ left: px(p.pitMid), boxShadow: "0 0 8px rgba(255,36,56,0.8)" }}
        />
        <div
          className="absolute top-1/2 h-[10px] w-[2px] -translate-y-1/2 bg-white/40"
          style={{ left: px(lap) }}
          title="current lap"
        />
      </div>
      <div className="num flex justify-between text-[9px] text-[--color-ink-3]">
        <span>L{p.pitLo}</span>
        <span className="text-[--color-accent-soft] font-bold">
          window peak L{p.pitMid} · P(stop) {fmtPct(p.pitP)}
        </span>
        <span>L{p.pitHi}</span>
      </div>
    </div>
  );
}

/** Win-probability sparkline for one driver, drawn only up to the current
 *  lap — no peeking at the rest of the race during a replay. */
function Spark({ num, color }: { num: number; color: string }) {
  const { lap } = useReplay();
  const W = 300, H = 54;
  const pts = RACE.laps
    .slice(0, lap + 1)
    .map((l, i) => {
      const p = l.p[String(num)]?.win ?? 0;
      return `${i ? "L" : "M"}${((i / MAX_LAP) * W).toFixed(1)},${(H - 2 - p * (H - 6)).toFixed(1)}`;
    })
    .join("");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
      {[0, 0.5, 1].map((g) => (
        <line
          key={g}
          x1="0" x2={W}
          y1={H - 2 - g * (H - 6)} y2={H - 2 - g * (H - 6)}
          stroke="rgba(255,255,255,0.07)"
          strokeDasharray="3 5"
        />
      ))}
      <path
        d={pts} fill="none" stroke={color} strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round"
        style={{ filter: `drop-shadow(0 0 4px ${color}66)` }}
      />
      <line
        x1={(lap / MAX_LAP) * W} x2={(lap / MAX_LAP) * W} y1="0" y2={H}
        stroke="#ff2438" strokeWidth="1"
      />
    </svg>
  );
}

export default function DriverDrawer({
  driver,
  onClose,
}: {
  driver: DriverMeta | null;
  onClose: () => void;
}) {
  const { lap } = useReplay();

  useEffect(() => {
    if (!driver) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [driver, onClose]);

  return (
    <AnimatePresence>
      {driver && (
        <>
          <motion.div
            key="backdrop"
            className="fixed inset-0 z-40 bg-black/50 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            key="panel"
            className="glass-strong fixed right-3 top-3 bottom-3 z-50 w-[min(400px,92vw)] overflow-y-auto rounded-2xl p-5"
            initial={{ x: 440, opacity: 0.6 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 440, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 32 }}
          >
            {(() => {
              const k = String(driver.num);
              const p = RACE.laps[lap].p[k];
              const t = RACE.laps[lap].t[k];
              if (!p || !t) return null;
              return (
                <>
                  {/* header */}
                  <div
                    className="relative -m-5 mb-4 overflow-hidden rounded-t-2xl p-5 pb-4"
                    style={{
                      background: `linear-gradient(135deg, ${driver.color}2e, transparent 60%)`,
                    }}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2.5">
                          <span
                            className="h-8 w-[5px] rounded-full"
                            style={{ background: driver.color, boxShadow: `0 0 12px ${driver.color}` }}
                          />
                          <span className="font-display text-[30px] font-bold leading-none tracking-wide">
                            {driver.code}
                          </span>
                          <span className="num mt-1 text-[12px] text-[--color-ink-3]">
                            #{driver.num}
                          </span>
                        </div>
                        <div className="mt-1.5 text-[11px] uppercase tracking-[0.18em] text-[--color-ink-2]">
                          {driver.team} · Grid P{driver.grid}
                        </div>
                      </div>
                      <button
                        onClick={onClose}
                        className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 bg-white/5 text-[--color-ink-2] transition hover:bg-white/12"
                        aria-label="Close"
                      >
                        ✕
                      </button>
                    </div>
                    <div className="num mt-3 flex gap-4 text-[11px] text-[--color-ink-2]">
                      <span>
                        {t.out ? "OUT" : `P${t.pos}`}
                      </span>
                      <span>Stops {t.pits}</span>
                      <span>xP {p.xp.toFixed(2)}</span>
                      <span>DNF risk {fmtPct(p.dnf)}</span>
                    </div>
                  </div>

                  {/* gauges */}
                  <div className="flex justify-around">
                    <Gauge value={p.win} label="Win" color="#ff2438" />
                    <Gauge value={p.pod} label="Podium" color={driver.color} />
                    <Gauge value={p.t10} label="Top 10" color="#8b86ff" />
                  </div>

                  <h3 className="mt-5 mb-2 text-[10px] font-bold uppercase tracking-[0.24em] text-[--color-ink-3]">
                    Finish position distribution
                  </h3>
                  <Histogram dist={p.dist} />

                  <h3 className="mt-5 mb-2 text-[10px] font-bold uppercase tracking-[0.24em] text-[--color-ink-3]">
                    Next pit stop window
                  </h3>
                  <PitWindow num={driver.num} />

                  <h3 className="mt-5 mb-2 text-[10px] font-bold uppercase tracking-[0.24em] text-[--color-ink-3]">
                    Win probability — race arc
                  </h3>
                  <Spark num={driver.num} color={driver.color} />

                  <p className="num mt-4 text-[9px] leading-relaxed text-[--color-ink-3]">
                    All quantities estimated from {RACE.session.nSims.toLocaleString()} Monte
                    Carlo race continuations at lap {lap}. Tyre state, pace posterior,
                    hazards and strategy heuristics per APEXODDS model bundle.
                  </p>
                </>
              );
            })()}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
