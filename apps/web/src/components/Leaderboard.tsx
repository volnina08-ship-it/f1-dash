"use client";

import { memo, useMemo } from "react";
import { motion } from "framer-motion";
import { RACE, useReplay, useTweened } from "@/lib/replay";
import type { DriverMeta, ProbRow, TimingRow } from "@/lib/types";
import {
  COMPOUND_COLORS,
  COMPOUND_NAMES,
  fmtGap,
  fmtInterval,
  fmtLapTime,
  fmtPct,
} from "@/lib/format";

const SECTOR_FLAG_COLORS = ["rgba(255,255,255,0.16)", "#2fd07a", "#c26bff"];

function TyreChip({ t }: { t: TimingRow }) {
  const color = COMPOUND_COLORS[t.cmp] ?? "#ccc";
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={`${COMPOUND_NAMES[t.cmp] ?? t.cmp} — ${t.age} laps old`}
    >
      <span
        className="num grid h-[22px] w-[22px] place-items-center rounded-full border-2 text-[10px] font-bold"
        style={{ borderColor: color, color }}
      >
        {t.cmp}
      </span>
      <span className="num text-[10.5px] text-[--color-ink-3]">{t.age}</span>
    </span>
  );
}

function Sectors({ t }: { t: TimingRow }) {
  if (!t.s || !t.sf)
    return <span className="text-[10px] text-[--color-ink-3]">···</span>;
  return (
    <span className="flex items-center gap-[3px]">
      {t.sf.map((f, i) => (
        <span
          key={i}
          className="h-[5px] w-[16px] rounded-full"
          style={{ background: SECTOR_FLAG_COLORS[f] }}
          title={`S${i + 1} ${(t.s![i] / 1000).toFixed(3)}`}
        />
      ))}
    </span>
  );
}

/** Animated probability cell: tweened number + slim bar + flash on jumps. */
function ProbCell({
  value,
  accent = false,
}: {
  value: number;
  accent?: boolean;
}) {
  const shown = useTweened(value);
  const pct = Math.max(0, Math.min(1, shown));
  const hot = accent && value >= 0.35;
  return (
    <div className="relative w-[54px]">
      <div
        className={`num text-[12.5px] font-semibold leading-tight ${
          hot ? "text-[--color-accent-soft]" : ""
        }`}
        style={hot ? { textShadow: "0 0 14px rgba(255,36,56,0.6)" } : undefined}
      >
        {fmtPct(pct)}
      </div>
      <div className="mt-[3px] h-[3px] w-full overflow-hidden rounded-full bg-white/8">
        <div
          className="h-full rounded-full"
          style={{
            width: `${pct * 100}%`,
            background: accent
              ? "linear-gradient(90deg,#8f0f21,#ff2438,#ff7a45)"
              : "rgba(255,255,255,0.4)",
            boxShadow: accent ? "0 0 8px rgba(255,36,56,0.5)" : undefined,
            transition: "width 0.5s cubic-bezier(0.3,0,0.2,1)",
          }}
        />
      </div>
    </div>
  );
}

function Trend({ delta }: { delta: number }) {
  if (Math.abs(delta) < 0.015)
    return <span className="text-[10px] text-[--color-ink-3]">—</span>;
  const up = delta > 0;
  return (
    <motion.span
      key={`${up}-${Math.round(delta * 100)}`}
      initial={{ y: up ? 5 : -5, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      className={`num inline-flex items-center gap-0.5 text-[10.5px] font-bold ${
        up ? "text-[#5fe39a]" : "text-[#ff7d88]"
      }`}
      title="Win probability change over the last 5 laps"
    >
      {up ? "▲" : "▼"} {Math.abs(delta * 100).toFixed(0)}
    </motion.span>
  );
}

const Row = memo(function Row({
  d,
  t,
  p,
  trendDelta,
  flash,
  onSelect,
}: {
  d: DriverMeta;
  t: TimingRow;
  p: ProbRow;
  trendDelta: number;
  flash: boolean;
  onSelect: (num: number) => void;
}) {
  const isLeader = t.pos === 1 && !t.out;
  return (
    <motion.button
      layout="position"
      transition={{ type: "spring", stiffness: 380, damping: 36 }}
      onClick={() => onSelect(d.num)}
      className={`group relative grid w-full grid-cols-[30px_4px_56px_66px_1fr] items-center gap-x-3 rounded-xl border border-transparent px-2.5 py-[7px] text-left outline-none transition-colors duration-300 hover:border-white/15 hover:bg-white/6 sm:grid-cols-[30px_4px_56px_64px_62px_62px_74px_66px_30px_repeat(3,60px)_44px_40px] ${
        t.out ? "opacity-35 saturate-50" : ""
      }`}
      style={
        flash
          ? { background: "rgba(255,36,56,0.10)" }
          : isLeader
            ? { background: "rgba(255,255,255,0.035)" }
            : undefined
      }
    >
      {/* POS */}
      <motion.span
        key={t.pos}
        initial={{ scale: 1.35, color: "#ff6672" }}
        animate={{ scale: 1, color: "#f2f1f6" }}
        transition={{ duration: 0.45 }}
        className="num text-center text-[13px] font-bold"
      >
        {t.out ? "–" : t.pos}
      </motion.span>

      {/* team bar */}
      <span
        className="h-6 w-[4px] rounded-full"
        style={{ background: d.color, boxShadow: `0 0 10px ${d.color}66` }}
      />

      {/* code */}
      <span className="flex flex-col leading-none">
        <span className="font-display text-[14px] font-bold tracking-wide">
          {d.code}
        </span>
        <span className="mt-[3px] truncate text-[9px] uppercase tracking-[0.12em] text-[--color-ink-3]">
          {d.team}
        </span>
      </span>

      {/* gap */}
      <span
        className={`num text-[11.5px] ${isLeader ? "font-bold text-[--color-accent-soft]" : "text-[--color-ink]"}`}
      >
        {t.out ? "OUT" : fmtGap(t.gap, t.ld, isLeader)}
      </span>

      {/* interval */}
      <span className="num hidden text-[11.5px] text-[--color-ink-2] sm:block">
        {t.out ? "" : fmtInterval(t.int, isLeader)}
      </span>

      {/* last lap */}
      <span className="num hidden text-[11.5px] text-[--color-ink-2] sm:block">
        {t.out ? "" : fmtLapTime(t.last)}
      </span>

      {/* sectors */}
      <span className="hidden sm:block">{!t.out && <Sectors t={t} />}</span>

      {/* tyre */}
      <span className="hidden sm:block">{!t.out && <TyreChip t={t} />}</span>

      {/* pits */}
      <span className="num hidden text-center text-[11px] text-[--color-ink-2] sm:block">
        {t.pits}
      </span>

      {/* probabilities */}
      <span className="hidden sm:block">
        <ProbCell value={p.win} accent />
      </span>
      <span className="hidden sm:block">
        <ProbCell value={p.pod} />
      </span>
      <span className="hidden sm:block">
        <ProbCell value={p.t10} />
      </span>

      {/* xP */}
      <span className="num hidden text-[11.5px] text-[--color-ink-2] sm:block">
        {t.out ? "" : p.xp.toFixed(1)}
      </span>

      {/* trend */}
      <span className="hidden text-right sm:block">
        {!t.out && <Trend delta={trendDelta} />}
      </span>

      {/* mobile probability summary */}
      <span className="col-span-full mt-1 flex gap-4 sm:hidden">
        <span className="num text-[11px]">
          WIN <b className="text-[--color-accent-soft]">{fmtPct(p.win)}</b>
        </span>
        <span className="num text-[11px]">POD {fmtPct(p.pod)}</span>
        <span className="num text-[11px]">xP {p.xp.toFixed(1)}</span>
      </span>
    </motion.button>
  );
});

const HEADERS = [
  ["POS", "text-center"],
  ["", ""],
  ["DRIVER", ""],
  ["GAP", ""],
  ["INT", "hidden sm:block"],
  ["LAST", "hidden sm:block"],
  ["SECTORS", "hidden sm:block"],
  ["TYRE", "hidden sm:block"],
  ["PIT", "hidden sm:block text-center"],
  ["WIN", "hidden sm:block"],
  ["POD", "hidden sm:block"],
  ["TOP10", "hidden sm:block"],
  ["xP", "hidden sm:block"],
  ["Δ5", "hidden sm:block text-right"],
] as const;

export default function Leaderboard({
  onSelect,
}: {
  onSelect: (num: number) => void;
}) {
  const { lap } = useReplay();
  const data = RACE.laps[lap];
  const prev = RACE.laps[Math.max(0, lap - 5)];
  const flashPrev = RACE.laps[Math.max(0, lap - 1)];

  const ordered = useMemo(
    () =>
      [...RACE.drivers].sort(
        (a, b) =>
          (data.t[String(a.num)]?.pos ?? 99) - (data.t[String(b.num)]?.pos ?? 99)
      ),
    [data]
  );

  return (
    <section className="glass rounded-2xl p-3">
      <div className="mb-1 grid grid-cols-[30px_4px_56px_66px_1fr] gap-x-3 px-2.5 pb-2 pt-1 sm:grid-cols-[30px_4px_56px_64px_62px_62px_74px_66px_30px_repeat(3,60px)_44px_40px]">
        {HEADERS.map(([h, cls], i) => (
          <span
            key={i}
            className={`text-[9px] font-semibold uppercase tracking-[0.18em] text-[--color-ink-3] ${cls}`}
          >
            {h}
          </span>
        ))}
      </div>
      <div className="flex flex-col gap-[3px]">
        {ordered.map((d) => {
          const k = String(d.num);
          const winNow = data.p[k].win;
          const winPrev = prev.p[k]?.win ?? winNow;
          const winLast = flashPrev.p[k]?.win ?? winNow;
          return (
            <Row
              key={d.num}
              d={d}
              t={data.t[k]}
              p={data.p[k]}
              trendDelta={winNow - winPrev}
              flash={Math.abs(winNow - winLast) > 0.06}
              onSelect={onSelect}
            />
          );
        })}
      </div>
    </section>
  );
}
