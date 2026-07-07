"use client";

import { motion } from "framer-motion";
import { MAX_LAP, useReplay } from "@/lib/replay";

export default function Controls() {
  const { lap, playing, speed, toggle, restart, seek, cycleSpeed, finished } =
    useReplay();

  return (
    <motion.div
      initial={{ y: 80, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ delay: 0.6, type: "spring", stiffness: 260, damping: 26 }}
      className="glass-strong fixed bottom-4 left-1/2 z-30 flex w-[min(620px,94vw)] -translate-x-1/2 items-center gap-3 rounded-2xl px-4 py-2.5"
    >
      <button
        onClick={restart}
        className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/5 text-[13px] transition hover:bg-white/12"
        title="Restart replay"
      >
        ⟲
      </button>

      <button
        onClick={toggle}
        className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-[#ff2438] to-[#a3132a] text-white shadow-[0_0_24px_rgba(255,36,56,0.45)] transition hover:brightness-110"
        title="Play / pause (space)"
      >
        {finished ? (
          <span className="text-[15px]">⟲</span>
        ) : playing ? (
          <svg viewBox="0 0 24 24" className="h-4.5 w-4.5 h-[18px] w-[18px]" fill="currentColor">
            <rect x="6" y="5" width="4" height="14" rx="1.2" />
            <rect x="14" y="5" width="4" height="14" rx="1.2" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" className="ml-[2px] h-[18px] w-[18px]" fill="currentColor">
            <path d="M7 4.8v14.4c0 .9 1 1.5 1.8 1L21 13c.8-.5.8-1.6 0-2.1L8.8 3.8C8 3.3 7 3.9 7 4.8Z" />
          </svg>
        )}
      </button>

      <button
        onClick={cycleSpeed}
        className="num h-9 w-12 shrink-0 rounded-xl border border-white/10 bg-white/5 text-[12px] font-bold transition hover:bg-white/12"
        title="Playback speed"
      >
        {speed}×
      </button>

      <input
        type="range"
        min={0}
        max={MAX_LAP}
        value={lap}
        onChange={(e) => seek(Number(e.target.value))}
        className="scrub w-full"
        style={{ ["--fill" as string]: `${(lap / MAX_LAP) * 100}%` }}
        aria-label="Scrub race lap"
      />

      <span className="num w-[72px] shrink-0 text-right text-[12px] font-semibold text-[--color-ink-2]">
        LAP {lap}
        <span className="text-[--color-ink-3]">/{MAX_LAP}</span>
      </span>
    </motion.div>
  );
}
