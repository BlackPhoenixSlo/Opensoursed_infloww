"use client";

/**
 * alertSounds — the 12 alert sounds for new messages and timed reminders
 * (roadmap W3 row 3.13; Infloww ships 12 choosable sounds, Audio1–12 /
 * timeOutAudio1..12, findings 04 M19 and 02 M24).
 *
 * Synthesised with WebAudio, so there are no audio files to ship or license.
 * One AudioContext per window, made on first use. Browsers keep it suspended
 * until the page has had a user gesture; the desktop app has no such rule.
 *
 * `playAlertOnce` is what the app calls on an arrival: every window (main +
 * popouts) runs its own toaster and hears the same SSE event, so a Web Lock
 * per key lets one window play it, and a short gap keeps a burst from
 * becoming a cacophony.
 */

export const ALERT_SOUND_IDS = [
  "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10", "s11", "s12",
] as const;
export type AlertSoundId = (typeof ALERT_SOUND_IDS)[number];

interface Note {
  /** Frequency in Hz. */
  f: number;
  /** Start, seconds after the sound starts. */
  t: number;
  /** Length in seconds. */
  d: number;
  wave?: OscillatorType;
  /** Glide to this frequency over the note. */
  to?: number;
  /** Relative level, default 1. */
  g?: number;
}

export interface AlertSound {
  id: AlertSoundId;
  label: string;
  notes: Note[];
}

export const ALERT_SOUNDS: AlertSound[] = [
  { id: "s1", label: "Chime", notes: [{ f: 880, t: 0, d: 0.3 }, { f: 1318.5, t: 0.12, d: 0.45 }] },
  { id: "s2", label: "Ding", notes: [{ f: 1568, t: 0, d: 0.6 }] },
  { id: "s3", label: "Pop", notes: [{ f: 600, to: 1200, t: 0, d: 0.08, wave: "triangle" }] },
  {
    id: "s4", label: "Bell",
    notes: [{ f: 660, t: 0, d: 0.9, g: 0.6 }, { f: 1320, t: 0, d: 0.6, g: 0.25 }, { f: 1980, t: 0, d: 0.3, g: 0.12 }],
  },
  {
    id: "s5", label: "Marimba",
    notes: [
      { f: 523.25, t: 0, d: 0.25, wave: "triangle" },
      { f: 659.25, t: 0.1, d: 0.25, wave: "triangle" },
      { f: 783.99, t: 0.2, d: 0.35, wave: "triangle" },
    ],
  },
  { id: "s6", label: "Glass", notes: [{ f: 2093, t: 0, d: 0.5, g: 0.5 }, { f: 2637, t: 0.08, d: 0.5, g: 0.5 }] },
  { id: "s7", label: "Bubble", notes: [{ f: 400, to: 900, t: 0, d: 0.12 }, { f: 500, to: 1100, t: 0.14, d: 0.12 }] },
  {
    id: "s8", label: "Alert",
    notes: [{ f: 880, t: 0, d: 0.12, wave: "square", g: 0.3 }, { f: 880, t: 0.18, d: 0.12, wave: "square", g: 0.3 }],
  },
  { id: "s9", label: "Pluck", notes: [{ f: 392, t: 0, d: 0.25, wave: "sawtooth", g: 0.3 }] },
  {
    id: "s10", label: "Rise",
    notes: [
      { f: 523.25, t: 0, d: 0.12, wave: "triangle" },
      { f: 659.25, t: 0.1, d: 0.12, wave: "triangle" },
      { f: 783.99, t: 0.2, d: 0.12, wave: "triangle" },
      { f: 1046.5, t: 0.3, d: 0.3, wave: "triangle" },
    ],
  },
  {
    id: "s11", label: "Triple",
    notes: [{ f: 1046.5, t: 0, d: 0.1 }, { f: 1046.5, t: 0.15, d: 0.1 }, { f: 1046.5, t: 0.3, d: 0.1 }],
  },
  { id: "s12", label: "Soft", notes: [{ f: 440, t: 0, d: 0.8, g: 0.5 }, { f: 554.37, t: 0.2, d: 0.8, g: 0.4 }] },
];

export function isAlertSoundId(v: unknown): v is AlertSoundId {
  return typeof v === "string" && (ALERT_SOUND_IDS as readonly string[]).includes(v);
}

const VOLUME = 0.3;
let ctx: AudioContext | null = null;

function audioContext(): AudioContext | null {
  if (ctx) return ctx;
  if (typeof window === "undefined") return null;
  const AC = window.AudioContext
    ?? (window as Window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AC) return null;
  try {
    ctx = new AC();
  } catch {
    return null;
  }
  return ctx;
}

/** A resume() that settles later than this is stale: the sound is dropped,
 *  so sounds requested while the context was suspended don't pile up and all
 *  play at once on the next user gesture. */
const RESUME_STALE_MS = 1_000;

/** Play one sound now. Returns false where there is no WebAudio. */
export function playAlertSound(id: AlertSoundId): boolean {
  const ac = audioContext();
  if (!ac) return false;
  const sound = ALERT_SOUNDS.find((s) => s.id === id) ?? ALERT_SOUNDS[0];
  if (ac.state === "running") return schedule(ac, sound);
  const askedAt = Date.now();
  ac.resume().then(
    () => {
      if (ac.state === "running" && Date.now() - askedAt < RESUME_STALE_MS) schedule(ac, sound);
    },
    () => {},
  );
  return true;
}

function schedule(ac: AudioContext, sound: AlertSound): boolean {
  try {
    const t0 = ac.currentTime + 0.02;
    for (const n of sound.notes) {
      const start = t0 + n.t;
      const end = start + n.d;
      const osc = ac.createOscillator();
      const gain = ac.createGain();
      osc.type = n.wave ?? "sine";
      osc.frequency.setValueAtTime(n.f, start);
      if (n.to) osc.frequency.exponentialRampToValueAtTime(n.to, end);
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(VOLUME * (n.g ?? 1), start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, end);
      osc.connect(gain);
      gain.connect(ac.destination);
      osc.start(start);
      osc.stop(end + 0.05);
    }
    return true;
  } catch {
    return false;
  }
}

/** How long a window holds a key's lock: covers SSE delivery skew between windows. */
const HOLD_MS = 10_000;
/** Minimum gap between two sounds in one window. */
const GAP_MS = 1_000;
let lastAt = 0;

function playGapped(id: AlertSoundId): void {
  const now = Date.now();
  if (now - lastAt < GAP_MS) return;
  lastAt = now;
  playAlertSound(id);
}

/** Play `id` for the arrival `key` in one window only (see the header). */
export function playAlertOnce(key: string, id: AlertSoundId): void {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (!locks?.request) {
    playGapped(id);
    return;
  }
  locks
    .request(`chatterly-alert-sound:${key}`, { ifAvailable: true }, async (lock) => {
      if (!lock) return;
      playGapped(id);
      await new Promise((r) => setTimeout(r, HOLD_MS));
    })
    .catch(() => {});
}
