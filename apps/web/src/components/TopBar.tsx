"use client";

import { RACE } from "@/lib/replay";

export default function TopBar() {
  return (
    <header className="glass sticky top-3 z-40 mx-auto flex max-w-[1660px] items-center gap-4 rounded-2xl px-4 py-2.5 sm:px-5">
      {/* brand */}
      <div className="flex items-center gap-3">
        <div className="relative grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-[#ff2438] to-[#8f0f21] shadow-[0_0_24px_rgba(255,36,56,0.45)]">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none">
            <path d="M12 3.5 L19 20.5 H15.6 L12 10.6 L8.4 20.5 H5 Z" fill="white" />
          </svg>
        </div>
        <div className="leading-tight">
          <div className="font-display text-[17px] font-700 tracking-[0.02em]">
            <span className="font-bold">APEX</span>
            <span className="text-[--color-accent-soft] font-bold">ODDS</span>
          </div>
          <div className="text-[9.5px] uppercase tracking-[0.28em] text-[--color-ink-3]">
            Live probability engine
          </div>
        </div>
      </div>

      <div className="mx-1 hidden h-8 w-px bg-white/10 sm:block" />

      {/* session */}
      <div className="hidden min-w-0 items-center gap-2.5 sm:flex">
        <span className="text-[15px]">🇭🇺</span>
        <div className="leading-tight">
          <div className="truncate text-[13px] font-semibold tracking-wide">
            {RACE.session.name}
          </div>
          <div className="num text-[10px] text-[--color-ink-3]">
            {RACE.session.circuit} · 2025 · Round 14
          </div>
        </div>
      </div>

      <span className="ml-1 inline-flex items-center gap-1.5 rounded-full border border-[--color-accent]/40 bg-[--color-accent]/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-[--color-accent-soft]">
        <span className="live-dot h-1.5 w-1.5 rounded-full bg-[--color-accent]" />
        Replay
      </span>

      <div className="ml-auto hidden items-center gap-4 lg:flex">
        <div className="num text-right text-[10.5px] leading-relaxed text-[--color-ink-3]">
          {RACE.session.nSims.toLocaleString()} worlds / lap · full recompute
          &lt;2s
          <br />
          Monte Carlo · vectorized engine
        </div>
      </div>
    </header>
  );
}
