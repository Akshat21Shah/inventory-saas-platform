"use client";

import { useCallback, useSyncExternalStore } from "react";

/** "Sound on new orders" per device (a convenience, so browser storage is enough). Off until the
 * user turns it on: browsers only allow sound after a tap anyway. */
const KEY = "orders.sound";
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "on";
  } catch {
    return false;
  }
}

function write(on: boolean) {
  try {
    window.localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    // storage unavailable: the choice lasts until the page reloads
  }
  listeners.forEach((listener) => listener());
}

let context: AudioContext | null = null;

/** A short two-note chime made on the device (no sound file to load). */
export function playChime() {
  if (!read() || typeof window === "undefined" || !("AudioContext" in window)) return;
  try {
    context ??= new AudioContext();
    const now = context.currentTime;
    [880, 1320].forEach((frequency, index) => {
      const osc = context!.createOscillator();
      const gain = context!.createGain();
      osc.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, now + index * 0.18);
      gain.gain.exponentialRampToValueAtTime(0.2, now + index * 0.18 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + index * 0.18 + 0.3);
      osc.connect(gain).connect(context!.destination);
      osc.start(now + index * 0.18);
      osc.stop(now + index * 0.18 + 0.32);
    });
  } catch {
    // no sound on this device
  }
}

export function useOrderSound() {
  const on = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    read,
    () => false,
  );
  const toggle = useCallback(() => {
    const next = !read();
    write(next);
    if (next) {
      context ??= typeof AudioContext === "undefined" ? null : new AudioContext();
      void context?.resume();
      playChime();
    }
  }, []);
  return { on, toggle };
}
