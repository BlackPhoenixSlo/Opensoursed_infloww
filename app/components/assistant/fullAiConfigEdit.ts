/**
 * Do-mode's `full_ai_config` (docs/spec/phase-03c-full-ai-one-click-setup.md, D63): "reply slower" → a proposed change
 * of the Creator's Full AI draft. The server proposes (service/assistant_full_ai.py: the fresh stored draft, the patch,
 * 03a's `validate`); Apply is the page's own rev-checked `PUT /admin/full-ai/config/draft`, one request. The checkpoint
 * is never touched — Save on the page makes the draft live. This file is the pure half the card and the runner read
 * (fullAiConfigEdit.test.ts).
 */

import { humanStyle, layersOff, type FullAiConfig } from "@/components/automations/fullAiTestChat";

/** One changed key (assistant_full_ai.diffs); `label` falls back to the key on the server. */
export interface ConfigDiff { field: string; label: string; before: unknown; after: unknown }

export interface FullAiConfigSlots {
  /** The draft's rev the proposal was built on: the PUT's base (a newer one → 409). */
  rev: number;
  before: FullAiConfig;
  after: FullAiConfig;
  diffs: ConfigDiff[];
  account_name: string;
}

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** The draft's slots, read defensively: null without a usable `rev` and `after` (nothing to apply). */
export function slotsFrom(raw: unknown): FullAiConfigSlots | null {
  if (!isObj(raw)) return null;
  const { rev, before, after, diffs, account_name } = raw;
  if (typeof rev !== "number" || !Number.isInteger(rev) || rev < 0 || !isObj(after)) return null;
  return {
    rev,
    before: isObj(before) ? before : {},
    after,
    diffs: Array.isArray(diffs)
      ? diffs.filter(isObj).filter((d) => typeof d.field === "string").map((d) => ({
        field: d.field as string, label: typeof d.label === "string" ? d.label : (d.field as string),
        before: d.before, after: d.after,
      }))
      : [],
    account_name: typeof account_name === "string" ? account_name : "",
  };
}

/** A value in plain words: "on", "off", "euryale-v2.3, hermes-4-405b". */
export function fmtValue(field: string, v: unknown): string {
  if (field === "style" && isObj(v)) {
    const cfg = { style: v };
    const hs = humanStyle(cfg);
    return hs === "mixed" ? `${layersOff(cfg)} off` : hs;
  }
  if (typeof v === "boolean") return v ? "on" : "off";
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.length ? v.map(String).join(", ") : "none";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** "Reply speed: 0-2m → 0-15-60". */
export const diffLine = (d: ConfigDiff) => `${d.label}: ${fmtValue(d.field, d.before)} → ${fmtValue(d.field, d.after)}`;

/** The apply PUT's body: the proposal's whole draft on its rev. */
export function applyBody(slots: FullAiConfigSlots, accountId: string) {
  return { account_id: accountId, draft: slots.after, rev: slots.rev };
}

export const APPLIED_LINE = "Draft updated. Save on the page makes it the checkpoint.";
export const STALE_LINE = "The draft changed since you saw it. Ask again.";

/** The PUT's answers that end a config run (any other error fails it). */
export type ConfigStatus = 200 | 409 | 422;

/** The card's result line for the PUT's status and body (422: `{errors: ["key: why"]}`). */
export function resultLine(status: ConfigStatus, body: unknown): string {
  if (status === 200) return APPLIED_LINE;
  if (status === 409) return STALE_LINE;
  const errs = isObj(body) && Array.isArray(body.errors) ? body.errors.map(String) : [];
  return errs.length ? `Not applied: ${errs.join("; ")}` : "Not applied: the server refused the change.";
}
