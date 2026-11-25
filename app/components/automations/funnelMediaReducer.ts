import type { FunnelAccountMedia, FunnelMediaSave, FunnelStepMedia } from "@/hooks/useFunnels";

export interface StepDraft {
  ids: number[];
  previewCount: number;
}

export type Slot = "opener" | number;

export type PickerTarget = Slot | null;

export interface FunnelMediaState {
  openerIds: number[];
  steps: Record<string, StepDraft>;
  pickerFor: PickerTarget;
  seeded: boolean;
  done: boolean;
  rev: number;
}

export type FunnelMediaAction =
  | { type: "hydrate"; media: FunnelAccountMedia; stepNos: number[] }
  | { type: "setOpener"; ids: number[] }
  | { type: "setStep"; stepNo: number; patch: Partial<StepDraft> }
  | { type: "copyToAll"; fromStepNo: number; stepNos: number[] }
  | { type: "move"; target: Slot; i: number; dir: -1 | 1 }
  | { type: "remove"; target: Slot; i: number }
  | { type: "openPicker"; target: Slot }
  | { type: "closePicker" }
  | { type: "pickConfirm"; ids: number[] }
  | { type: "saveStart" }
  | { type: "saveOk"; rev: number };

export const initialFunnelMedia: FunnelMediaState = {
  openerIds: [],
  steps: {},
  pickerFor: null,
  seeded: false,
  done: false,
  rev: 0,
};

const EMPTY: StepDraft = { ids: [], previewCount: 0 };

export function stepDraft(ids: number[], previewCount: number): StepDraft {
  return { ids, previewCount: Math.max(0, Math.min(previewCount, ids.length)) };
}

// Order matters: the first previewCount ids go out FREE as the teaser.
function reorder(ids: number[], i: number, dir: -1 | 1): number[] {
  const j = i + dir;
  if (j < 0 || j >= ids.length) return ids;
  const next = [...ids];
  [next[i], next[j]] = [next[j], next[i]];
  return next;
}

function edited(s: FunnelMediaState, patch: Partial<FunnelMediaState>): FunnelMediaState {
  return { ...s, ...patch, done: false, rev: s.rev + 1 };
}

function patchStep(s: FunnelMediaState, stepNo: number, patch: Partial<StepDraft>): FunnelMediaState {
  const k = String(stepNo);
  const d = { ...(s.steps[k] ?? EMPTY), ...patch };
  return edited(s, { steps: { ...s.steps, [k]: stepDraft(d.ids, d.previewCount) } });
}

export function funnelMediaReducer(s: FunnelMediaState, a: FunnelMediaAction): FunnelMediaState {
  switch (a.type) {
    case "hydrate": {
      // Seed once: a later refetch (the save's own invalidate) must not clobber edits.
      if (s.seeded) return s;
      const steps: Record<string, StepDraft> = {};
      for (const stepNo of a.stepNos) {
        const m = a.media.steps_media?.[String(stepNo)];
        const ids = (m?.media_files ?? []).filter((n) => n > 0);
        steps[String(stepNo)] = stepDraft(ids, (m?.previews ?? []).length);
      }
      return {
        ...s,
        openerIds: (a.media.opening_media_ids ?? []).filter((n) => n > 0),
        steps,
        seeded: true,
      };
    }
    case "setOpener":
      return edited(s, { openerIds: a.ids });
    case "setStep":
      return patchStep(s, a.stepNo, a.patch);
    case "copyToAll": {
      const src = s.steps[String(a.fromStepNo)];
      if (!src || src.ids.length === 0) return s;
      const steps = { ...s.steps };
      for (const stepNo of a.stepNos) {
        if (stepNo === a.fromStepNo) continue;
        steps[String(stepNo)] = stepDraft([...src.ids], src.previewCount);
      }
      return edited(s, { steps });
    }
    case "move": {
      if (a.target === "opener") return edited(s, { openerIds: reorder(s.openerIds, a.i, a.dir) });
      return patchStep(s, a.target, { ids: reorder(s.steps[String(a.target)]?.ids ?? [], a.i, a.dir) });
    }
    case "remove": {
      if (a.target === "opener") return edited(s, { openerIds: s.openerIds.filter((_, k) => k !== a.i) });
      const d = s.steps[String(a.target)];
      if (!d) return s;
      return patchStep(s, a.target, { ids: d.ids.filter((_, k) => k !== a.i) });
    }
    case "openPicker":
      return { ...s, pickerFor: a.target };
    case "closePicker":
      return { ...s, pickerFor: null };
    case "pickConfirm": {
      const t = s.pickerFor;
      if (t == null) return s;
      const next = t === "opener"
        ? edited(s, { openerIds: a.ids })
        : patchStep(s, t, { ids: a.ids });
      return { ...next, pickerFor: null };
    }
    case "saveStart":
      return { ...s, done: false };
    case "saveOk":
      return a.rev === s.rev ? { ...s, done: true } : s;
  }
}

export function pickerIds(s: FunnelMediaState): number[] {
  if (s.pickerFor === "opener") return s.openerIds;
  if (s.pickerFor != null) return s.steps[String(s.pickerFor)]?.ids ?? [];
  return [];
}

export function buildPayload(
  openerIds: number[],
  steps: Record<string, StepDraft>,
  stepNos: number[],
): Required<FunnelMediaSave> {
  const steps_media: Record<string, FunnelStepMedia> = {};
  for (const stepNo of stepNos) {
    const d = steps[String(stepNo)];
    if (!d || d.ids.length === 0) continue;
    steps_media[String(stepNo)] = {
      media_files: d.ids,
      previews: d.ids.slice(0, Math.min(d.previewCount, d.ids.length)),
    };
  }
  return { opening_media_ids: openerIds, steps_media };
}
