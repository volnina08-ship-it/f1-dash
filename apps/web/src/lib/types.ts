export interface DriverMeta {
  num: number;
  code: string;
  team: string;
  color: string;
  grid: number;
}

export interface TimingRow {
  pos: number;
  gap: number; // ms to leader
  int: number; // ms to car ahead
  last: number | null; // last lap ms
  s: [number, number, number] | null; // sector ms
  sf: [number, number, number] | null; // 0 normal / 1 personal best / 2 session best
  cmp: string; // compound letter M/H/S/I/W
  age: number;
  pits: number;
  ld: number; // laps down
  out: boolean;
}

export interface ProbRow {
  win: number;
  pod: number;
  t10: number;
  xp: number;
  dnf: number;
  pitP: number;
  pitLo: number;
  pitMid: number;
  pitHi: number;
  dist: number[]; // P(finish position i+1)
}

export type TrackStatus = "GREEN" | "SC" | "VSC" | "RED";

export interface LapData {
  lap: number;
  status: TrackStatus;
  t: Record<string, TimingRow>;
  p: Record<string, ProbRow>;
}

export interface RaceEvent {
  lap: number;
  type:
    | "info"
    | "start"
    | "sc"
    | "vsc"
    | "green"
    | "pit"
    | "dnf"
    | "lead"
    | "model"
    | "finish";
  text: string;
}

export interface RaceData {
  session: {
    key: string;
    name: string;
    circuit: string;
    country: string;
    totalLaps: number;
    nSims: number;
    overtakeDifficulty: number;
    pitLossS: number;
  };
  drivers: DriverMeta[];
  laps: LapData[];
  events: RaceEvent[];
}
