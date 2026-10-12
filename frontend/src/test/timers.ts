import { act } from "@testing-library/react";
import { vi } from "vitest";

/**
 * Advances fake timers in small act() steps. A single large step would batch every
 * React update until the end, so effect-scheduled timers (created after a render)
 * would never get the chance to fire inside the window being simulated.
 */
export async function advanceInSteps(totalMs: number, stepMs = 500): Promise<void> {
  let remaining = totalMs;
  while (remaining > 0) {
    const step = Math.min(stepMs, remaining);
    await act(() => vi.advanceTimersByTimeAsync(step));
    remaining -= step;
  }
}
