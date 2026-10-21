import { beforeAll, describe, expect, it, vi } from "vitest";

import { ALERT_SOUNDS, ALERT_SOUND_IDS, isAlertSoundId, playAlertOnce, playAlertSound } from "./alertSounds";

/** Records every oscillator a sound starts. */
const started: { type: string; freq: number }[] = [];

class FakeParam {
  value = 0;
  setValueAtTime(v: number) { this.value = v; }
  exponentialRampToValueAtTime() {}
}
class FakeAudioContext {
  static last: FakeAudioContext | null = null;
  state = "running";
  currentTime = 0;
  destination = {};
  /** What the next resume() does; default: runs at once. */
  onResume: () => Promise<void> = () => { this.state = "running"; return Promise.resolve(); };
  constructor() { FakeAudioContext.last = this; }
  resume() { return this.onResume(); }
  createGain() { return { gain: new FakeParam(), connect() {} }; }
  createOscillator() {
    const osc = {
      type: "sine",
      frequency: new FakeParam(),
      connect() {},
      start() { started.push({ type: osc.type, freq: osc.frequency.value }); },
      stop() {},
    };
    return osc;
  }
}

beforeAll(() => {
  vi.stubGlobal("AudioContext", FakeAudioContext);
});

describe("alert sounds", () => {
  it("has 12 presets with unique ids, each with at least one note", () => {
    expect(ALERT_SOUNDS).toHaveLength(12);
    expect(ALERT_SOUNDS.map((s) => s.id)).toEqual([...ALERT_SOUND_IDS]);
    for (const s of ALERT_SOUNDS) expect(s.notes.length).toBeGreaterThan(0);
  });

  it("validates ids", () => {
    expect(isAlertSoundId("s12")).toBe(true);
    expect(isAlertSoundId("s13")).toBe(false);
    expect(isAlertSoundId(3)).toBe(false);
  });

  it("plays a preset as one oscillator per note", () => {
    started.length = 0;
    expect(playAlertSound("s4")).toBe(true);
    expect(started.map((o) => o.freq)).toEqual([660, 1320, 1980]);
  });

  it("a suspended context plays after resume, but drops a sound whose resume settles late", async () => {
    playAlertSound("s2"); // make sure the context exists
    const ac = FakeAudioContext.last!;
    started.length = 0;

    ac.state = "suspended";
    playAlertSound("s2");
    expect(started).toHaveLength(0); // nothing scheduled while suspended
    await Promise.resolve();
    expect(started).toHaveLength(1);

    vi.useFakeTimers();
    try {
      started.length = 0;
      ac.state = "suspended";
      let release!: () => void;
      ac.onResume = () => new Promise<void>((r) => { release = () => { ac.state = "running"; r(); }; });
      playAlertSound("s2");
      vi.advanceTimersByTime(5_000); // the user gestures much later
      release();
      await Promise.resolve();
      await Promise.resolve();
      expect(started).toHaveLength(0);
    } finally {
      vi.useRealTimers();
      ac.state = "running";
    }
  });

  it("playAlertOnce: one window per key holds the lock, the others stay quiet", async () => {
    const held = new Set<string>();
    const locks = {
      request: async (name: string, _opts: unknown, cb: (lock: unknown) => Promise<void>) => {
        if (held.has(name)) return cb(null);
        held.add(name);
        void cb({ name }); // held until the callback settles, which the test never awaits
      },
    };
    Object.defineProperty(navigator, "locks", { value: locks, configurable: true });
    try {
      started.length = 0;
      playAlertOnce("m1", "s2");
      playAlertOnce("m1", "s2"); // a popout hearing the same message
      await Promise.resolve();
      expect(started).toHaveLength(1);
    } finally {
      delete (navigator as { locks?: unknown }).locks;
    }
  });
});
