/**
 * The funnel editor's draft model (automations/FunnelEditor): wire
 * FunnelStep ⇄ editable DraftStep, and the raw-JSON codec over the whole
 * funnel body. Raw steps go through the same `toDraft` → `toWire` checks as
 * the typed form — plus the fields `toDraft` would otherwise silently coerce
 * (a non-object step, an unknown `type`, a non-number `price`, a bad or
 * duplicate `step` number, non-list `messages` / `check_intervals_min`).
 *
 * `step` is the step's id (`next` targets and per-model PPV media key on it;
 * the walker goes by list order). `DraftStep.step` is the one source of truth:
 * kept through every edit, move and remove, written by `toWire`; a new step
 * (added, or unnumbered in raw text) gets max + 1.
 */

import type { FunnelFull, FunnelStep, PpvStep } from "@/hooks/useFunnels";
import { parseJsonObject, type RawJsonCodec } from "@/lib/rawJsonReducer";
import { mergeCaptions } from "@/lib/parseCaptions";

// ── Local draft model (easy to edit; converted to/from wire FunnelStep) ──

export type StepKind = "reply" | "ppv";

export interface DraftStep {
  kind: StepKind;
  /** The wire `step` id (see the module doc). */
  step: number;
  /** Poll cadence after this step as a comma list of minutes (blank → executor default). */
  intervals: string;
  /** Message VARIANT pool (used when `generate` is off). */
  messages: string[];
  /** Generate the reply/copy with the AI instead of static messages. */
  generate: boolean;
  prompt: string;
  // PPV only (media is per-account → FunnelMediaPane, not here):
  price: string;
  lockedText: boolean;
  /** Step keys the typed form doesn't model (e.g. legacy in-step media, or a
   *  field a raw-JSON edit added) — carried through toDraft→toWire so a
   *  raw → typed → save round-trip never silently drops them. */
  extra: Record<string, unknown>;
}

/** Step keys the typed editor owns (re-emitted by `toWire`) — everything else is
 *  stashed in `DraftStep.extra` and merged back on save. */
const KNOWN_STEP_KEYS = new Set([
  "type", "step", "messages", "generate", "prompt", "price",
  "locked_text", "check_intervals_min",
]);

export function blankStep(kind: StepKind, step: number): DraftStep {
  return {
    kind,
    step,
    intervals: "",
    messages: [""],
    generate: false,
    prompt: "",
    price: kind === "ppv" ? "0" : "",
    lockedText: false,
    extra: {},
  };
}

/** A wire step → editor draft. Keys the form doesn't model are preserved in
 *  `extra`; known keys come back in the form's shape — a `prompt` beside
 *  static messages is dropped (static wins on the server too). A missing PPV
 *  price stays blank (server default), never $0. */
export function toDraft(step: FunnelStep): DraftStep {
  const isPpv = step.type === "paid_ppv";
  const msgs = Array.isArray(step.messages) ? step.messages.map(String) : [];
  const hasStatic = msgs.some((m) => m.trim());
  const generate = !hasStatic && Boolean(step.generate || (step.prompt && step.prompt.trim()));
  const ivRaw = step.check_intervals_min;
  const intervals = Array.isArray(ivRaw) ? ivRaw.join(", ") : "";
  const ppv = step as PpvStep;
  const extra: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(step)) {
    if (!KNOWN_STEP_KEYS.has(k)) extra[k] = v;
  }
  return {
    kind: isPpv ? "ppv" : "reply",
    step: step.step,
    intervals,
    messages: msgs.length ? msgs : [""],
    generate,
    prompt: step.prompt ?? "",
    price: isPpv && typeof ppv.price === "number" ? String(ppv.price) : "",
    lockedText: isPpv ? Boolean(ppv.locked_text) : false,
    extra,
  };
}

/** Parse a comma/space list of positive whole ints; throws on a bad token. */
function parseIntervals(raw: string, label: string): number[] {
  const parts = raw.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
  const out: number[] = [];
  for (const p of parts) {
    const n = Number(p);
    if (!Number.isInteger(n) || n <= 0) {
      throw new Error(`${label} interval "${p}" must be a positive whole number of minutes`);
    }
    out.push(n);
  }
  return out;
}

/** Draft → wire step (throws with a clear message on invalid input). */
export function toWire(d: DraftStep, idx: number): FunnelStep {
  const label = `Step ${idx + 1}`;
  const msgs = d.messages.map((m) => m.trim()).filter(Boolean);
  if (!d.generate && msgs.length === 0) {
    throw new Error(`${label} needs at least one message (or switch it to AI-generated).`);
  }
  // TEXT-ONLY: PPV media is per-account (FunnelMediaPane), never written here.
  const out: Omit<PpvStep, "type"> & { type?: "paid_ppv" } = { step: d.step };
  if (d.kind === "ppv") {
    out.type = "paid_ppv";
    if (d.price.trim() !== "") {
      const price = Number(d.price);
      if (!Number.isInteger(price) || price < 0) {
        throw new Error(`${label} price must be a whole number ≥ 0.`);
      }
      out.price = price;
    }
    if (d.lockedText) out.locked_text = true;
  }
  // The walker waits on a PPV step's cadence too (reply_mass_funnel._step_intervals).
  const intervals = parseIntervals(d.intervals, label);
  if (intervals.length) out.check_intervals_min = intervals;
  if (d.generate) {
    out.generate = true;
    if (d.prompt.trim()) out.prompt = d.prompt.trim();
  } else {
    out.messages = msgs;
  }
  // Merge preserved unknown keys; the fields we set above win over `extra`.
  return { ...d.extra, ...out } as FunnelStep;
}

// ── The whole funnel (header + steps) ───────────────────────────────────

export interface FunnelDraft {
  name: string;
  description: string;
  opening: string;
  steps: DraftStep[];
}

export interface FunnelBody {
  name: string;
  opening_message: string;
  description: string | null;
  steps: FunnelStep[];
}

export const EMPTY_FUNNEL: FunnelDraft = { name: "", description: "", opening: "", steps: [] };

export function funnelDraftOf(f: FunnelFull): FunnelDraft {
  return {
    name: f.name,
    description: f.description ?? "",
    opening: f.opening_message,
    steps: (f.steps ?? []).map(toDraft),
  };
}

/** A typed-form edit, applied by `editFunnel`. */
export type FunnelEdit =
  | { type: "header"; patch: Partial<Pick<FunnelDraft, "name" | "description" | "opening">> }
  | { type: "addStep"; kind: StepKind }
  | { type: "patchStep"; i: number; patch: Partial<DraftStep> }
  | { type: "removeStep"; i: number }
  | { type: "moveStep"; i: number; dir: -1 | 1 }
  | { type: "patchMsg"; i: number; mi: number; text: string }
  | { type: "addMsg"; i: number }
  /** Imported captions: replace a lone blank variant, else append (dupes skipped). */
  | { type: "addMsgs"; i: number; texts: string[] }
  | { type: "removeMsg"; i: number; mi: number };

/** The id for a new step: max(existing) + 1. */
function nextStepNumber(steps: Pick<DraftStep, "step">[]): number {
  return steps.reduce((m, s) => Math.max(m, s.step), 0) + 1;
}

/** One typed-form edit (pure). Out-of-range moves and removing the last
 *  message variant are no-ops. */
export function editFunnel(d: FunnelDraft, e: FunnelEdit): FunnelDraft {
  const mapStep = (i: number, f: (s: DraftStep) => DraftStep) =>
    ({ ...d, steps: d.steps.map((s, idx) => (idx === i ? f(s) : s)) });
  switch (e.type) {
    case "header":
      return { ...d, ...e.patch };
    case "addStep":
      return { ...d, steps: [...d.steps, blankStep(e.kind, nextStepNumber(d.steps))] };
    case "patchStep":
      return mapStep(e.i, (s) => ({ ...s, ...e.patch }));
    case "removeStep":
      return { ...d, steps: d.steps.filter((_, idx) => idx !== e.i) };
    case "moveStep": {
      const j = e.i + e.dir;
      if (j < 0 || j >= d.steps.length) return d;
      const steps = d.steps.slice();
      [steps[e.i], steps[j]] = [steps[j], steps[e.i]];
      return { ...d, steps };
    }
    case "patchMsg":
      return mapStep(e.i, (s) => ({ ...s, messages: s.messages.map((m, k) => (k === e.mi ? e.text : m)) }));
    case "addMsg":
      return mapStep(e.i, (s) => ({ ...s, messages: [...s.messages, ""] }));
    case "addMsgs":
      return mapStep(e.i, (s) => ({ ...s, messages: mergeCaptions(s.messages, e.texts).pool }));
    case "removeMsg":
      return mapStep(e.i, (s) =>
        s.messages.length <= 1 ? s : { ...s, messages: s.messages.filter((_, k) => k !== e.mi) });
  }
}

/** Draft → body, steps wired (throws on an invalid step or a reused step
 *  number). Name / opener may be blank — `saveBody` requires them. */
function wireBody(d: FunnelDraft): FunnelBody {
  const steps = d.steps.map(toWire);
  const seen = new Set<number>();
  steps.forEach((s, i) => {
    if (seen.has(s.step)) throw new Error(`Step ${i + 1} reuses step number ${s.step}.`);
    seen.add(s.step);
  });
  return {
    name: d.name.trim(),
    opening_message: d.opening.trim(),
    description: d.description.trim() || null,
    steps,
  };
}

/** The body to save (throws with a clear message). */
export function saveBody(d: FunnelDraft): FunnelBody {
  if (!d.name.trim()) throw new Error("Name is required.");
  if (!d.opening.trim()) throw new Error("Opening message is required.");
  return wireBody(d);
}

/** Narrows one raw step to the wire shape `toDraft` reads (throws otherwise). */
function assertRawStep(s: unknown, idx: number): asserts s is FunnelStep {
  const label = `Step ${idx + 1}`;
  if (typeof s !== "object" || s === null || Array.isArray(s)) throw new Error(`${label} must be an object.`);
  const o = s as Record<string, unknown>;
  if (o.step != null && (typeof o.step !== "number" || !Number.isInteger(o.step) || o.step < 1)) {
    throw new Error(`${label} step must be a whole number ≥ 1.`);
  }
  if (o.type != null && o.type !== "paid_ppv") {
    throw new Error(`${label} has unknown type ${JSON.stringify(o.type)} (only "paid_ppv").`);
  }
  if (o.type === "paid_ppv" && o.price != null && typeof o.price !== "number") {
    throw new Error(`${label} price must be a whole number ≥ 0.`);
  }
  if (o.messages != null && !Array.isArray(o.messages)) throw new Error(`${label} messages must be a list.`);
  if (o.check_intervals_min != null && !Array.isArray(o.check_intervals_min)) {
    throw new Error(`${label} check_intervals_min must be a list of minutes.`);
  }
}

/** Raw steps → drafts; an unnumbered step (no `step`) gets max + 1. */
function rawDraftSteps(raw: unknown[]): DraftStep[] {
  const steps = raw.map((s, i) => {
    assertRawStep(s, i);
    return s;
  });
  let next = nextStepNumber(steps.filter((s) => s.step != null));
  return steps.map((s) => toDraft(s.step != null ? s : { ...s, step: next++ }));
}

/** Raw-JSON codec over `{ name, opening_message, description, steps }`. */
export const FUNNEL_RAW: RawJsonCodec<FunnelDraft> = {
  format: (d) => JSON.stringify(wireBody(d), null, 2),
  parse(text) {
    const o = parseJsonObject(text, "Funnel", '{ "name": "…", "opening_message": "…", "steps": [] }');
    const steps = o.steps ?? [];
    if (!Array.isArray(steps)) throw new Error("steps must be a list.");
    const draft: FunnelDraft = {
      name: String(o.name ?? "").trim(),
      description: o.description == null ? "" : String(o.description).trim(),
      opening: String(o.opening_message ?? "").trim(),
      steps: rawDraftSteps(steps),
    };
    wireBody(draft); // reject here what a save would
    return draft;
  },
};
