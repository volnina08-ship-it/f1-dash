"use client";

import { useMemo } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { RACE, useReplay } from "@/lib/replay";
import type { RaceEvent } from "@/lib/types";

const STYLE: Record<
  RaceEvent["type"],
  { icon: string; cls: string }
> = {
  info: { icon: "ℹ", cls: "text-[--color-ink-2]" },
  start: { icon: "🚦", cls: "text-[#7fe7ae]" },
  sc: { icon: "⚠", cls: "text-[--color-flag-sc]" },
  vsc: { icon: "⚠", cls: "text-[--color-flag-vsc]" },
  green: { icon: "🟢", cls: "text-[#7fe7ae]" },
  pit: { icon: "🛞", cls: "text-[--color-ink]" },
  dnf: { icon: "✕", cls: "text-[--color-accent-soft]" },
  lead: { icon: "▶", cls: "text-white" },
  model: { icon: "∿", cls: "text-[--color-accent-soft]" },
  finish: { icon: "🏁", cls: "text-white" },
};

export default function EventFeed() {
  const { lap } = useReplay();

  const visible = useMemo(
    () => RACE.events.filter((e) => e.lap <= lap).slice(-40).reverse(),
    [lap]
  );

  return (
    <section className="glass flex min-h-0 flex-col rounded-2xl p-4">
      <h2 className="font-display mb-2 flex items-center gap-2 text-[13px] font-bold uppercase tracking-[0.2em]">
        Race feed
        <span className="live-dot ml-1 h-1.5 w-1.5 rounded-full bg-[--color-accent]" />
      </h2>
      <div className="feed -mr-2 flex max-h-[300px] flex-col gap-[3px] overflow-y-auto pr-2">
        <AnimatePresence initial={false}>
          {visible.map((e, i) => {
            const s = STYLE[e.type] ?? STYLE.info;
            const isModel = e.type === "model";
            return (
              <motion.div
                key={`${e.lap}-${e.text}`}
                layout
                initial={{ opacity: 0, y: -10, filter: "blur(4px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3, delay: i === 0 ? 0.05 : 0 }}
                className={`flex items-start gap-2.5 rounded-lg border px-2.5 py-[6px] ${
                  isModel
                    ? "border-[--color-accent]/25 bg-[--color-accent]/8"
                    : "border-transparent bg-white/3"
                }`}
              >
                <span className={`w-4 text-center text-[11px] ${s.cls}`}>{s.icon}</span>
                <span className="num mt-[1px] w-8 shrink-0 text-[9.5px] font-bold text-[--color-ink-3]">
                  L{e.lap}
                </span>
                <span
                  className={`text-[11px] leading-snug ${
                    isModel ? "text-[--color-accent-soft]" : "text-[--color-ink-2]"
                  }`}
                >
                  {e.text}
                </span>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </section>
  );
}
