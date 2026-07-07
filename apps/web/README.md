# APEXODDS web dashboard (Phase 1 / M5)

Next.js 15 + Tailwind timing-tower UI, per the brief §8:

- **Leaderboard**: POS | driver (team color) | gap | int | last lap |
  S1 S2 S3 | tyre + age | pits | **WIN%** | **POD%** | **TOP10%** | xP |
  trend arrow — probability cells animate on change.
- **Win Probability Chart**: full-race time series, top 6 highlighted,
  SC/pit/overtake event markers.
- **Race state bar** (lap, track status, weather) + **event feed** with the
  model's reactions ("SC deployed → NOR win% 18→27%").
- **Replay mode first**: streams `ws://…/ws/replay/{session_key}` from the
  backtest snapshots (see `apexodds/api/main.py`) — the demo works with no
  live subscription. Live mode (M6) reuses the same message shape.

Design: dark timing-tower aesthetic, monospace numerals (JetBrains Mono),
team colors as accents, own identity (KZH-independent). No F1 trademarks;
footer must carry "Unofficial — not associated with Formula 1".

Scaffold when M5 starts:

```bash
npx create-next-app@latest . --ts --tailwind --app
```
