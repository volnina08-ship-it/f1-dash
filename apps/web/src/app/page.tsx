"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { ReplayProvider, RACE } from "@/lib/replay";
import Background from "@/components/Background";
import TopBar from "@/components/TopBar";
import RaceBar from "@/components/RaceBar";
import Leaderboard from "@/components/Leaderboard";
import WinChart from "@/components/WinChart";
import StatTiles from "@/components/StatTiles";
import EventFeed from "@/components/EventFeed";
import DriverDrawer from "@/components/DriverDrawer";
import Controls from "@/components/Controls";
import type { DriverMeta } from "@/lib/types";

const stagger = {
  hidden: { opacity: 0, y: 18, filter: "blur(6px)" },
  show: (i: number) => ({
    opacity: 1,
    y: 0,
    filter: "blur(0px)",
    transition: { delay: 0.12 + i * 0.09, duration: 0.55, ease: [0.25, 0, 0.2, 1] as const },
  }),
};

export default function Page() {
  const [selected, setSelected] = useState<DriverMeta | null>(null);

  return (
    <ReplayProvider>
      <Background />
      <div className="mx-auto max-w-[1660px] px-3 pb-28 pt-3 sm:px-5">
        <TopBar />
        <RaceBar />

        <main className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]">
          <motion.div variants={stagger} custom={0} initial="hidden" animate="show">
            <Leaderboard
              onSelect={(num) =>
                setSelected(RACE.drivers.find((d) => d.num === num) ?? null)
              }
            />
          </motion.div>

          <div className="flex min-w-0 flex-col gap-3 xl:sticky xl:top-[76px] xl:self-start">
            <motion.div variants={stagger} custom={1} initial="hidden" animate="show">
              <WinChart />
            </motion.div>
            <motion.div variants={stagger} custom={2} initial="hidden" animate="show">
              <StatTiles />
            </motion.div>
            <motion.div variants={stagger} custom={3} initial="hidden" animate="show">
              <EventFeed />
            </motion.div>
          </div>
        </main>

        <footer className="num mt-8 pb-2 text-center text-[9.5px] leading-relaxed text-[--color-ink-3]">
          APEXODDS · Monte Carlo probability engine · replay of a synthetic
          demonstration race, probabilities computed by the real engine
          <br />
          Unofficial — not associated with Formula 1. Non-commercial
          development &amp; calibration demo.
        </footer>
      </div>

      <Controls />
      <DriverDrawer driver={selected} onClose={() => setSelected(null)} />
    </ReplayProvider>
  );
}
