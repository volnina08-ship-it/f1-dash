"use client";

import { RACE, useReplay, useTweened } from "@/lib/replay";

function Tile({
  label,
  value,
  sub,
  bar,
}: {
  label: string;
  value: string;
  sub: string;
  bar?: number; // 0..1 mini meter
}) {
  return (
    <div className="glass flex-1 rounded-xl px-3.5 py-3">
      <div className="text-[9px] font-semibold uppercase tracking-[0.22em] text-[--color-ink-3]">
        {label}
      </div>
      <div className="num mt-1 text-[19px] font-semibold leading-none">{value}</div>
      {bar !== undefined && (
        <div className="mt-2 h-[3px] w-full overflow-hidden rounded-full bg-white/8">
          <div
            className="h-full rounded-full bg-gradient-to-r from-[#8f0f21] to-[#ff2438]"
            style={{ width: `${bar * 100}%` }}
          />
        </div>
      )}
      <div className="num mt-1.5 text-[9.5px] text-[--color-ink-3]">{sub}</div>
    </div>
  );
}

/** Live model telemetry: what the engine is doing right now. */
export default function StatTiles() {
  const { lap } = useReplay();
  const data = RACE.laps[lap];

  // Entropy of the win distribution — "how open is this race?"
  const wins = RACE.drivers.map((d) => data.p[String(d.num)]?.win ?? 0);
  const entropy = -wins.reduce((s, p) => (p > 0 ? s + p * Math.log2(p) : s), 0);
  const openness = Math.min(1, entropy / Math.log2(8));
  const shownOpen = useTweened(openness);

  const leader = RACE.drivers
    .map((d) => ({ d, p: data.p[String(d.num)] }))
    .sort((a, b) => (b.p?.win ?? 0) - (a.p?.win ?? 0))[0];
  const shownLead = useTweened(leader?.p?.win ?? 0);

  const running = RACE.drivers.filter(
    (d) => !(data.t[String(d.num)]?.out ?? false)
  ).length;

  return (
    <div className="flex gap-2.5">
      <Tile
        label="Race openness"
        value={`${Math.round(shownOpen * 100)}`}
        sub="entropy of win distribution"
        bar={shownOpen}
      />
      <Tile
        label="Title favourite"
        value={`${leader?.d.code ?? "—"} ${Math.round(shownLead * 100)}%`}
        sub={`${RACE.session.nSims.toLocaleString()} worlds resimulated`}
        bar={shownLead}
      />
      <Tile
        label="Cars running"
        value={`${running}/20`}
        sub={`overtake difficulty ${RACE.session.overtakeDifficulty.toFixed(2)}`}
        bar={running / 20}
      />
    </div>
  );
}
