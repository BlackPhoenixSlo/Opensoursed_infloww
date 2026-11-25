import { humanStyle, layersOff, type FullAiConfig } from "@/components/automations/fullAiConfig";

export interface ConfigDiff { field: string; label: string; before: unknown; after: unknown }

export interface FullAiConfigSlots {
  /** The draft rev the proposal was built on: the PUT's base (a newer one gives 409). */
  rev: number;
  before: FullAiConfig;
  after: FullAiConfig;
  diffs: ConfigDiff[];
  account_name: string;
}

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

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

export const diffLine = (d: ConfigDiff) => `${d.label}: ${fmtValue(d.field, d.before)} → ${fmtValue(d.field, d.after)}`;

export function applyBody(slots: FullAiConfigSlots, accountId: string) {
  return { account_id: accountId, draft: slots.after, rev: slots.rev };
}

export const APPLIED_LINE = "Draft updated. Make draft live on the page copies it to the Live settings.";
export const STALE_LINE = "The draft changed since you saw it. Ask again.";

export type ConfigStatus = 200 | 409 | 422;

export function resultLine(status: ConfigStatus, body: unknown): string {
  if (status === 200) return APPLIED_LINE;
  if (status === 409) return STALE_LINE;
  const errs = isObj(body) && Array.isArray(body.errors) ? body.errors.map(String) : [];
  return errs.length ? `Not applied: ${errs.join("; ")}` : "Not applied: the server refused the change.";
}
