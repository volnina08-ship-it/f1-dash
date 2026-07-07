"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import raw from "@/data/race.json";
import type { RaceData } from "./types";

export const RACE = raw as unknown as RaceData;

export const MAX_LAP = RACE.laps.length - 1;
const LAP_MS = 1700; // wall-clock per race lap at 1x

interface ReplayState {
  lap: number;
  playing: boolean;
  speed: number;
  finished: boolean;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seek: (lap: number) => void;
  restart: () => void;
  cycleSpeed: () => void;
}

const Ctx = createContext<ReplayState | null>(null);

export function ReplayProvider({ children }: { children: ReactNode }) {
  const [lap, setLap] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(2);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Auto-start the broadcast after a beat (feels live, not static).
  useEffect(() => {
    const t = setTimeout(() => setPlaying(true), 1400);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (timer.current) clearInterval(timer.current);
    if (!playing) return;
    timer.current = setInterval(() => {
      setLap((l) => {
        if (l >= MAX_LAP) {
          setPlaying(false);
          return l;
        }
        return l + 1;
      });
    }, LAP_MS / speed);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [playing, speed]);

  const seek = useCallback((l: number) => {
    setLap(Math.max(0, Math.min(MAX_LAP, Math.round(l))));
  }, []);

  const value = useMemo<ReplayState>(
    () => ({
      lap,
      playing,
      speed,
      finished: lap >= MAX_LAP,
      play: () => setPlaying(lap >= MAX_LAP ? false : true),
      pause: () => setPlaying(false),
      toggle: () =>
        setPlaying((p) => {
          if (lap >= MAX_LAP) {
            setLap(0);
            return true;
          }
          return !p;
        }),
      seek,
      restart: () => {
        setLap(0);
        setPlaying(true);
      },
      cycleSpeed: () => setSpeed((s) => (s >= 8 ? 1 : s * 2)),
    }),
    [lap, playing, speed, seek]
  );

  // Space bar = play/pause, arrows = scrub.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.code === "Space") {
        e.preventDefault();
        value.toggle();
      } else if (e.code === "ArrowRight") value.seek(lap + 1);
      else if (e.code === "ArrowLeft") value.seek(lap - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [value, lap]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useReplay(): ReplayState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useReplay outside ReplayProvider");
  return ctx;
}

/** Smoothly tween a number toward its target (for probability counters). */
export function useTweened(target: number, ms = 650): number {
  const [value, setValue] = useState(target);
  const ref = useRef({ from: target, to: target, start: 0 });
  const raf = useRef<number>(0);

  useEffect(() => {
    ref.current = { from: value, to: target, start: performance.now() };
    cancelAnimationFrame(raf.current);
    const step = (now: number) => {
      const t = Math.min(1, (now - ref.current.start) / ms);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(ref.current.from + (ref.current.to - ref.current.from) * eased);
      if (t < 1) raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, ms]);

  return value;
}
