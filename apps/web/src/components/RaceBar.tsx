"use client";

import { AnimatePresence, motion } from "framer-motion";
import { MAX_LAP, RACE, useReplay } from "@/lib/replay";

const STATUS_STYLES: Record<string, { label: string; cls: string; dot: string }> = {
  GREEN: {
    label: "Track clear",
    cls: "border-[--color-flag-green]/40 bg-[--color-flag-green]/10 text-[#7fe7ae]",
    dot: "bg-[--color-flag-green]",
  },
  SC: {
    label: "Safety car",
    cls: "border-[--color-flag-sc]/50 bg-[--color-flag-sc]/12 text-[#ffd97a]",
    dot: "bg-[--color-flag-sc]",
  },
  VSC: {
    label: "Virtual SC",
    cls: "border-[--color-flag-vsc]/50 bg-[--color-flag-vsc]/12 text-[#ffc38f]",
    dot: "bg-[--color-flag-vsc]",
  },
  RED: {
    label: "Red flag",
    cls: "border-[--color-accent]/50 bg-[--color-accent]/12 text-[--color-accent-soft]",
    dot: "bg-[--color-accent]",
  },
};

/** Race distance strip: SC/VSC bands + playhead over a gradient fill. */
function ProgressStrip() {
  const { lap, seek } = useReplay();
  const pct = (lap / MAX_LAP) * 100;

  const bands: { from: number; to: number; kind: string }[] = [];
  let open: { from: number; kind: string } | null = null;
  RACE.laps.forEach((l) => {
    const kind = l.status === "SC" || l.status === "VSC" ? l.status : null;
    if (kind && !open) open = { from: l.lap, kind };
    if (open && (!kind || kind !== open.kind)) {
      bands.push({ from: open.from, to: l.lap, kind: open.kind });
      open = kind ? { from: l.lap, kind } : null;
    }
  });

  return (
    <div
      className="group relative h-9 flex-1 cursor-pointer"
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        seek(((e.clientX - r.left) / r.width) * MAX_LAP);
      }}
      title="Click to seek"
    >
      <div className="absolute inset-x-0 top-1/2 h-[6px] -translate-y-1/2 overflow-hidden rounded-full bg-white/8">
        <motion.div
          className="h-full rounded-full bg-gradient-to-r from-[#8f0f21] via-[#ff2438] to-[#ff7a45]"
          style={{ boxShadow: "0 0 16px rgba(255,36,56,0.55)" }}
          animate={{ width: `${pct}%` }}
          transition={{ type: "tween", duration: 0.5, ease: "easeOut" }}
        />
      </div>
      {bands.map((b, i) => (
        <div
          key={i}
          className="absolute top-1/2 h-[6px] -translate-y-1/2 rounded-sm"
          style={{
            left: `${(b.from / MAX_LAP) * 100}%`,
            width: `${((b.to - b.from) / MAX_LAP) * 100}%`,
            background:
              b.kind === "SC" ? "rgba(255,194,51,0.65)" : "rgba(255,161,75,0.55)",
          }}
          title={b.kind === "SC" ? "Safety Car" : "Virtual Safety Car"}
        />
      ))}
      <motion.div
        className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-[--color-accent] bg-white shadow-[0_0_14px_rgba(255,36,56,0.9)]"
        animate={{ left: `${pct}%` }}
        transition={{ type: "tween", duration: 0.5, ease: "easeOut" }}
      />
    </div>
  );
}

export default function RaceBar() {
  const { lap, finished } = useReplay();
  const status = finished ? "FINISH" : RACE.laps[lap].status;
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.GREEN;

  return (
    <section className="glass mx-auto mt-3 flex max-w-[1660px] flex-wrap items-center gap-x-6 gap-y-3 rounded-2xl px-5 py-3.5">
      {/* lap counter */}
      <div className="flex items-baseline gap-2.5">
        <span className="text-[10px] font-semibold uppercase tracking-[0.3em] text-[--color-ink-3]">
          Lap
        </span>
        <div className="num flex items-baseline text-[30px] font-semibold leading-none">
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.span
              key={lap}
              initial={{ y: 14, opacity: 0, filter: "blur(4px)" }}
              animate={{ y: 0, opacity: 1, filter: "blur(0px)" }}
              exit={{ y: -14, opacity: 0, filter: "blur(4px)" }}
              transition={{ duration: 0.28, ease: [0.3, 0, 0.2, 1] }}
              className="inline-block min-w-[2ch] text-right"
            >
              {lap}
            </motion.span>
          </AnimatePresence>
          <span className="text-[15px] text-[--color-ink-3]">/{MAX_LAP}</span>
        </div>
      </div>

      <ProgressStrip />

      {/* track status */}
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={status}
          initial={{ scale: 0.85, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.85, opacity: 0 }}
          transition={{ type: "spring", stiffness: 500, damping: 30 }}
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-[11px] font-bold uppercase tracking-[0.14em] ${
            status === "FINISH"
              ? "border-white/25 bg-white/10 text-white"
              : s.cls
          }`}
        >
          {status === "FINISH" ? (
            <>🏁 Chequered flag</>
          ) : (
            <>
              <span className={`live-dot h-2 w-2 rounded-full ${s.dot}`} />
              {s.label}
            </>
          )}
        </motion.span>
      </AnimatePresence>

      {/* context chips */}
      <div className="num hidden items-center gap-2 text-[10.5px] text-[--color-ink-2] xl:flex">
        <span className="rounded-md border border-white/10 bg-white/4 px-2 py-1">
          ☀ 27°C · Track 43°C
        </span>
        <span className="rounded-md border border-white/10 bg-white/4 px-2 py-1">
          Overtake difficulty {RACE.session.overtakeDifficulty.toFixed(2)}
        </span>
        <span className="rounded-md border border-white/10 bg-white/4 px-2 py-1">
          Pit loss ~{RACE.session.pitLossS.toFixed(0)}s
        </span>
      </div>
    </section>
  );
}
