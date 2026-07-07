"use client";

import { RACE, useReplay } from "@/lib/replay";

/** Layered ambient background: drifting red aurora, grid, noise, vignette.
 *  Shifts amber while the Safety Car is out. */
export default function Background() {
  const { lap } = useReplay();
  const status = RACE.laps[lap]?.status ?? "GREEN";
  const intervention = status === "SC" || status === "VSC";

  return (
    <div className="fixed inset-0 -z-10 overflow-hidden" aria-hidden>
      <div className="absolute inset-0 bg-[#08070c]" />
      {/* red aurora, top left */}
      <div
        className="blob blob-a -top-[28%] -left-[18%] h-[75vh] w-[60vw] transition-opacity duration-1000"
        style={{
          background:
            "radial-gradient(closest-side, rgba(255,36,56,0.34), rgba(255,36,56,0.10) 55%, transparent)",
          opacity: intervention ? 0.35 : 0.85,
        }}
      />
      {/* violet counterweight, right */}
      <div
        className="blob blob-b top-[8%] -right-[22%] h-[70vh] w-[52vw]"
        style={{
          background:
            "radial-gradient(closest-side, rgba(94,58,197,0.20), rgba(94,58,197,0.06) 55%, transparent)",
        }}
      />
      {/* deep red floor glow */}
      <div
        className="blob blob-b -bottom-[35%] left-[16%] h-[70vh] w-[62vw]"
        style={{
          background:
            "radial-gradient(closest-side, rgba(151,18,34,0.22), transparent 70%)",
        }}
      />
      {/* SC amber wash */}
      <div
        className="absolute inset-0 transition-opacity duration-1000"
        style={{
          background:
            "radial-gradient(ellipse 80% 55% at 50% -10%, rgba(255,194,51,0.16), transparent 65%)",
          opacity: intervention ? 1 : 0,
        }}
      />
      <div className="bg-grid absolute inset-0" />
      <div className="bg-noise absolute inset-0" />
      {/* vignette */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 120% 90% at 50% 20%, transparent 55%, rgba(0,0,0,0.55))",
        }}
      />
    </div>
  );
}
