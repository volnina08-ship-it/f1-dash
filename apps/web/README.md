# APEXODDS web dashboard (Phase 1 / M5)

Next.js 15 replay dashboard: glassmorphism dark UI with red accent,
Framer Motion leaderboard (animated position swaps, tweened probability
counters), win-probability chart with SC/VSC bands + crosshair tooltip,
model-reaction race feed, per-driver drawer (probability gauges, finish
distribution histogram, pit-window strip), and full replay transport
(play/pause/speed/scrub, space + arrow keys).

The demo replays a scripted 2025 Hungarian GP whose probabilities were
computed lap-by-lap by the **real APEXODDS engine** (2,500 Monte Carlo
worlds per lap) and baked into `src/data/race.json` — the page is fully
static, no backend needed. Phase 1b swaps the JSON for the live
WebSocket feed (`apexodds/api`) with the same message shape.

## Develop

```bash
cd apps/web
npm install
npm run dev          # http://localhost:3000
npm run build        # production build (static)
```

Regenerate the demo race (from the repo root, needs the Python venv):

```bash
.venv/bin/python scripts/make_demo_race.py        # ~10 min: 71 engine runs
```

## Deploy (Vercel)

New project: import the GitHub repo at
[vercel.com/new](https://vercel.com/new/import?s=https://github.com/volnina08-ship-it/f1-dash)
and set **Root Directory = `apps/web`** — everything else is
auto-detected (Next.js, `npm run build`), no environment variables
needed. Every push then redeploys via the Vercel git integration.

Design: dark timing-tower aesthetic, JetBrains Mono numerals, Space
Grotesk display, team colors as entity-locked accents (validated for CVD
separation/contrast on the dark surface; teammates distinguished by dash
pattern + direct labels).

*Unofficial — not associated with Formula 1.*
