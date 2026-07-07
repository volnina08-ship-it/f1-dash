export function fmtLapTime(ms: number | null | undefined): string {
  if (!ms || ms <= 0) return "—";
  const total = ms / 1000;
  const m = Math.floor(total / 60);
  const s = total - m * 60;
  return `${m}:${s.toFixed(3).padStart(6, "0")}`;
}

export function fmtGap(ms: number, lapsDown: number, isLeader: boolean): string {
  if (isLeader) return "LEADER";
  if (lapsDown >= 1) return `+${lapsDown} LAP${lapsDown > 1 ? "S" : ""}`;
  return `+${(ms / 1000).toFixed(1)}`;
}

export function fmtInterval(ms: number, isLeader: boolean): string {
  if (isLeader) return "—";
  return `+${(ms / 1000).toFixed(1)}`;
}

export function fmtPct(p: number, decimals = 0): string {
  const v = p * 100;
  if (v > 0 && v < 1) return "<1%";
  if (v > 99 && v < 100) return ">99%";
  return `${v.toFixed(decimals)}%`;
}

export function fmtSector(ms: number): string {
  return (ms / 1000).toFixed(3);
}

export const COMPOUND_COLORS: Record<string, string> = {
  S: "#ff3b47",
  M: "#ffd23f",
  H: "#e8e6f0",
  I: "#3fd07a",
  W: "#3f8bff",
};

export const COMPOUND_NAMES: Record<string, string> = {
  S: "Soft",
  M: "Medium",
  H: "Hard",
  I: "Intermediate",
  W: "Wet",
};
