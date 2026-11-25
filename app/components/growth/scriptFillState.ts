import type { FillOption, FillPlan, FillStatus, FillUndoEntry, FillUndoResult } from "@/lib/relay";
import {
  describeSweepText, errorCode, refusalText, sweepAbortedNote, sweepCounts, type SweepProgress,
} from "@/hooks/useVaultSweep";

export const DESCRIBE_TARGET = 1000;
const TARGET_TEXT = DESCRIBE_TARGET.toLocaleString("en-US");

export const SAVE_FIRST = "Save or close the open step first";

export const ASK_OWNER = "Ask the owner: filling uses the whole vault";

const FILL_ERRORS: Readonly<Record<string, string>> = {
  sequence_not_found: "This sequence has no steps any more. It was renamed or deleted: reload the page.",
  inventory_unknown: "The vault list could not be read just now. Try again in a minute.",
  account_id_required: "Pick a Creator first.",
  folder_not_allowed: ASK_OWNER,
};

export function fillRefusalText(err: unknown): string {
  const code = errorCode(err);
  return (code != null ? FILL_ERRORS[code] : undefined) ?? refusalText(err);
}

export interface FillNotice {
  account: string | null;
  sequence: string;
  undo: FillUndoEntry[];
  n: number;
  m: number;
}

export interface LeftCounts {
  changed: number;
  moved: number;
  reserved: number;
  other: number;
}

export interface FillDialogState {
  sequence: string;
  req: number;
  status: FillStatus | null;
  refusal: string | null;
}

export interface ScriptFillState {
  account: string | null;
  open: string | null;
  inflight: Readonly<Record<string, number>>;
  dialog: FillDialogState | null;
  notices: Readonly<Record<string, FillNotice>>;
  left: Readonly<Record<string, LeftCounts>>;
}

interface Pin {
  account: string | null;
  sequence: string;
  req: number;
}

export type Action =
  | { type: "show"; sequence: string | null }
  | ({ type: "press" } & Pin)
  | ({ type: "applied"; result: { applied: FillOption[]; undo: FillUndoEntry[] } } & Pin)
  | ({ type: "answered"; status: FillStatus } & Pin)
  | ({ type: "failed"; message: string } & Pin)
  | ({ type: "describeRefused"; message: string } & Pin)
  | ({ type: "undoPress" } & Pin)
  | ({ type: "undone"; result: FillUndoResult } & Pin)
  | { type: "dismiss"; account: string | null; sequence: string }
  | { type: "close" }
  | { type: "reset"; account: string | null };

export const INITIAL_FILL: ScriptFillState = {
  account: null, open: null, inflight: {}, dialog: null, notices: {}, left: {},
};

export function fillKey(account: string | null, sequence: string): string {
  return JSON.stringify([account, sequence]);
}

export function isLocked(s: ScriptFillState, account: string | null, sequence: string, listFailed: boolean): boolean {
  return listFailed || s.inflight[fillKey(account, sequence)] != null;
}

function without<T>(map: Readonly<Record<string, T>>, key: string): Record<string, T> {
  if (!(key in map)) return map;
  const rest = { ...map };
  delete rest[key];
  return rest;
}

function ended(s: ScriptFillState, a: Pin): ScriptFillState | null {
  const key = fillKey(a.account, a.sequence);
  if (s.inflight[key] !== a.req) return null;
  return { ...s, inflight: without(s.inflight, key) };
}

const shown = (s: ScriptFillState, a: Pin) => a.account === s.account && a.sequence === s.open;

export function scriptFillReducer(s: ScriptFillState, a: Action): ScriptFillState {
  switch (a.type) {
    case "show":
      if (s.open === a.sequence) return s;
      return { ...s, open: a.sequence, dialog: s.dialog?.sequence === a.sequence ? s.dialog : null };
    case "press":
    case "undoPress": {
      const key = fillKey(a.account, a.sequence);
      return { ...s, inflight: { ...s.inflight, [key]: a.req }, left: without(s.left, key) };
    }
    case "applied": {
      // Kept even when another Sequence or Creator is open: the write happened, and this is its only Undo.
      const e = ended(s, a);
      if (!e) return s;
      const key = fillKey(a.account, a.sequence);
      const { n, m } = noticeCounts(a.result.applied);
      const prev = e.notices[key];
      const notice: FillNotice = prev
        ? { ...prev, undo: [...prev.undo, ...a.result.undo], n: prev.n + n, m: prev.m + m }
        : { account: a.account, sequence: a.sequence, undo: a.result.undo, n, m };
      return {
        ...e,
        notices: { ...e.notices, [key]: notice },
        dialog: shown(s, a) && e.dialog?.sequence === a.sequence ? null : e.dialog,
      };
    }
    case "answered":
    case "failed": {
      const e = ended(s, a);
      if (!e) return s;
      if (!shown(s, a)) return e;
      const dialog: FillDialogState = a.type === "answered"
        ? { sequence: a.sequence, req: a.req, status: a.status, refusal: null }
        : { sequence: a.sequence, req: a.req, status: null, refusal: a.message };
      return { ...e, dialog };
    }
    case "describeRefused": {
      const d = s.dialog;
      if (a.account !== s.account || !d || d.sequence !== a.sequence || d.req !== a.req) return s;
      return { ...s, dialog: { ...d, refusal: a.message } };
    }
    case "undone": {
      const e = ended(s, a);
      if (!e) return s;
      const key = fillKey(a.account, a.sequence);
      const counts = leftNote(a.result);
      return {
        ...e,
        notices: without(e.notices, key),
        left: leftTotal(counts) > 0 ? { ...e.left, [key]: counts } : without(e.left, key),
      };
    }
    case "dismiss": {
      const key = fillKey(a.account, a.sequence);
      return { ...s, notices: without(s.notices, key), left: without(s.left, key) };
    }
    case "close":
      return s.dialog ? { ...s, dialog: null } : s;
    case "reset":
      return { ...s, account: a.account, dialog: null };
  }
}


export function noticeCounts(applied: readonly FillOption[]): { n: number; m: number } {
  const ids = new Set<number>();
  for (const o of applied) for (const id of [...o.media, ...o.previews]) ids.add(id);
  return { n: ids.size, m: new Set(applied.map((o) => o.step)).size };
}

const plural = (n: number, one: string) => `${n} ${n === 1 ? one : `${one}s`}`;

export function noticeText(notice: Pick<FillNotice, "n" | "m">): string {
  return `Added ${plural(notice.n, "item")} to ${plural(notice.m, "step")}`;
}

export function undoPayload(notice: FillNotice): { sequence: string; undo: FillUndoEntry[] } {
  return { sequence: notice.sequence, undo: notice.undo };
}

export function leftNote(result: FillUndoResult): LeftCounts {
  const c: LeftCounts = { changed: 0, moved: 0, reserved: 0, other: 0 };
  for (const k of result.kept) {
    switch (k.reason) {
      case "edited": c.changed++; break;
      case "moved":
      case "missing": c.moved++; break;
      case "reserved": c.reserved++; break;
      default: {
        const unknown: never = k.reason;
        void unknown;
        c.other++;
      }
    }
  }
  return c;
}

const leftTotal = (c: LeftCounts) => c.changed + c.moved + c.reserved + c.other;

export function leftText(c: LeftCounts): string {
  const parts = [
    c.changed ? `${c.changed} changed since the Fill` : "",
    c.moved ? `${c.moved} moved or deleted` : "",
    c.reserved ? `${c.reserved} in a sequence generated by a script source` : "",
    c.other ? `${c.other} could not be undone` : "",
  ].filter(Boolean);
  return `Undo left ${plural(leftTotal(c), "step")}: ${parts.join(", ")}.`;
}

function usd(cents: number): string {
  return cents % 100 ? `$${(cents / 100).toFixed(2)}` : `$${cents / 100}`;
}

const FIX = " — fix the price, then fill again.";

export function conflictLines(
  conflict: FillPlan["conflict"],
  options: readonly FillOption[],
): string[] {
  if (!conflict) return [];
  const { step: s, rule, price_cents: p } = conflict;
  const fixed = options.filter((o) => o.role === "paid_media" && o.price_fixed && o.price_cents > 0);
  const nearestEarlierAbove = (cents: number) =>
    fixed.filter((o) => o.step < s && o.price_cents > cents).sort((a, b) => b.step - a.step)[0];
  const nearestLaterBelow = (cents: number) =>
    fixed.filter((o) => o.step > s && o.price_cents < cents).sort((a, b) => a.step - b.step)[0];
  let line: string;
  switch (rule) {
  case "under_min": line = `Step ${s}: ${usd(p)} is under OnlyFans' $3 minimum`; break;
  case "over_max": line = `Step ${s}: ${usd(p)} is over the $200 cap`; break;
  case "below_earlier": {
    const ownFixed = fixed.some((o) => o.step === s && o.price_cents === p);
    const above = ownFixed ? nearestEarlierAbove(p) : undefined;
    if (above) line = `Step ${s} is priced below step ${above.step}`;
    else {
      const floor = fixed.filter((o) => o.step < s).sort((a, b) => b.price_cents - a.price_cents || b.step - a.step)[0];
      const ceiling = floor ? nearestLaterBelow(floor.price_cents) : undefined;
      line = floor && ceiling
        ? `Step ${floor.step} is priced above step ${ceiling.step}`
        : `Step ${s} cannot be priced between the steps around it`;
    }
    break;
  }
  case "quote_unholdable": {
    const above = nearestEarlierAbove(p);
    const below = nearestLaterBelow(p);
    line = above ? `Step ${s}: ${usd(p)} is priced below step ${above.step}`
      : below ? `Step ${s}: ${usd(p)} is priced above step ${below.step}`
        : `Step ${s}: ${usd(p)} is out of step order`;
    break;
  }
  default: {
    const unknown: never = rule;
    void unknown;
    line = `Step ${s}: ${usd(p)} breaks a price rule`;
  }
  }
  return [line + FIX];
}

export function canDescribe(plan: FillPlan | null | undefined): boolean {
  return !!plan && plan.status === "not_enough_content" && plan.describe.remaining > 0 && plan.describe.can_describe;
}

export interface SweepView {
  running: boolean;
  starting?: boolean;
  progress: SweepProgress | null;
}

export interface DialogCopy {
  title: string;
  lines: string[];
  note: { text: string; detail: string; tone: "warn" | "info" } | null;
  button: "describe" | "fill" | null;
}

const TITLE = "Fill with content";

const STATUS_LINE: Partial<Record<FillStatus, string>> = {
  no_fit: "This Creator's described content cannot fill every paid step of this sequence.",
  no_paid_steps: "No step in this sequence sells anything yet. Put a price on the steps that sell, then fill again.",
  already_filled: "Every step already has its content.",
  reserved: "This sequence is generated by a script source and is not filled.",
};
const FREE_UNFILLED_LINE =
  "Every paid step already has its content. No photo left is safe to send free, so the free steps stay empty.";

export function dialogFor(p: {
  status: FillStatus | null;
  plan: FillPlan | null | undefined;
  sweep: SweepView;
  refusal: string | null;
  now: number;
}): DialogCopy {
  const { plan, sweep, refusal } = p;
  if (refusal) return { title: TITLE, lines: [refusal], note: null, button: null };
  if (sweep.running || sweep.starting) {
    const counts = sweep.running ? sweepCounts(sweep.progress) : null;
    const extra = sweep.running && counts ? describeSweepText(sweep.progress).title.split("\n").slice(1) : [];
    const lines = [
      counts ? `Checked ${counts.done} of ${counts.total}. Keeps going if you close this.` : "starting…",
      ...extra,
    ];
    if (plan) lines.push(`${plan.describe.described} of ${plan.describe.target} described.`);
    return { title: "Describing content", lines, note: null, button: null };
  }
  const note = sweepAbortedNote(sweep.progress, p.now);
  const status = plan?.status ?? p.status;
  if (status === "ok") return { title: TITLE, lines: ["Ready to fill."], note, button: "fill" };
  if (status === "not_enough_content" && plan) {
    const d = plan.describe;
    if (canDescribe(plan)) {
      return {
        title: "Describe content first?",
        lines: [
          `This sequence needs more described vault content. Describe up to ${TARGET_TEXT} items for this Creator? ` +
            `${d.described} of ${d.target} done.`,
        ],
        note,
        button: "describe",
      };
    }
    if (d.remaining > 0) {
      const count = `This sequence needs more described vault content. ${d.described} of ${d.target} done.`;
      return { title: TITLE, lines: d.blocked_reason ? [count, d.blocked_reason] : [count], note, button: null };
    }
    return {
      title: TITLE,
      lines: [`Not enough content. ${d.described} of ${d.target} items are described and there is nothing left to describe.`],
      note,
      button: null,
    };
  }
  if ((status === "price_conflict" || status === "price_out_of_range") && plan) {
    return { title: TITLE, lines: conflictLines(plan.conflict, plan.options), note, button: null };
  }
  if (status === "already_filled" && plan?.options.some((o) => o.flags.includes("free_unfilled"))) {
    return { title: TITLE, lines: [FREE_UNFILLED_LINE], note, button: null };
  }
  const line = status ? STATUS_LINE[status] : undefined;
  return { title: TITLE, lines: [line ?? "Loading…"], note, button: null };
}
