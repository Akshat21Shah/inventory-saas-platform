import { afterEach } from "vitest";

/** Render the next components as if the screen were `width` px wide (reset after each test). */
export function setViewport(width: number) {
  (globalThis as { __testWidth?: number }).__testWidth = width;
}

afterEach(() => setViewport(1440));
