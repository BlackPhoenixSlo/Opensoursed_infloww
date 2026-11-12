/**
 * "Build AI folders" options: how many shoots stay script folders, the solo cut, and the OnlyFans mirror. All three
 * go into ONE apply payload and must match the preview the operator saw (the server re-derives the plan and retires
 * what it no longer makes), so they live in one pure reducer; VaultAiFoldersModal only dispatches.
 *
 * `confirmLabel` / `changesLine` turn the plan's `changes` (what Confirm does to the AI- folders already there) into
 * the copy shown before Confirm. Retiring a folder bound to an OnlyFans list unlinks that list, so the button says so.
 */

/** Shoots kept as their own folder: 0 (lanes only) .. 20, the route's range. */
export const KEEP_CHOICES: readonly number[] = Array.from({ length: 21 }, (_, i) => i);

export interface AiFoldersForm {
  keep: number;
  solo: boolean;
  mirrorToOf: boolean;
}

export type Action =
  | { type: "keep"; keep: number }
  | { type: "solo"; on: boolean }
  | { type: "mirror"; on: boolean };

export const INITIAL_FORM: AiFoldersForm = { keep: 2, solo: false, mirrorToOf: true };

export function aiFoldersFormReducer(state: AiFoldersForm, action: Action): AiFoldersForm {
  switch (action.type) {
    case "keep": {
      const keep = Math.max(0, Math.min(20, Math.trunc(action.keep) || 0));
      return keep === state.keep ? state : { ...state, keep };
    }
    case "solo":
      return action.on === state.solo ? state : { ...state, solo: action.on };
    case "mirror":
      return action.on === state.mirrorToOf ? state : { ...state, mirrorToOf: action.on };
  }
}

/** The apply call's options: exactly the preview's. */
export function buildPayload(form: AiFoldersForm): { keep: number; solo: boolean; mirrorToOf: boolean } {
  return { keep: form.keep, solo: form.solo, mirrorToOf: form.mirrorToOf };
}

export function keepLabel(n: number): string {
  if (n === 0) return "none (lanes only)";
  return `top ${n} ${n === 1 ? "shoot" : "shoots"}`;
}

/** What Confirm does to the AI- folders already there (the plan's `changes`). */
export interface PlanChanges {
  create: number;
  keep: number;
  retire: number;
  retire_on_of: number;
  retired: { folder_id: number; name: string; of_list_id: number | null }[];
}

export function canSubmit(busy: boolean, folders: number): boolean {
  return !busy && folders > 0;
}

/** "will create 3 · keep 9 · retire 2"; null before the plan lands. */
export function changesLine(changes: PlanChanges | null | undefined): string | null {
  if (!changes) return null;
  return `will create ${changes.create} · keep ${changes.keep} · retire ${changes.retire}`;
}

export function confirmLabel(opts: {
  busy: boolean;
  built: boolean;
  folders: number;
  changes: PlanChanges | null | undefined;
}): string {
  if (opts.busy) return "Creating…";
  const base = opts.built ? "Rebuild" : `Create ${opts.folders} folders`;
  const onOf = opts.changes?.retire_on_of ?? 0;
  return onOf > 0 ? `${base} · retire ${onOf} linked to OnlyFans` : base;
}
