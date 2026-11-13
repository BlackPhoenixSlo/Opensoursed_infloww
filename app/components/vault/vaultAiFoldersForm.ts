/**
 * "Build AI folders" options: how many shoots stay script folders, the solo cut, the OnlyFans mirror, the ticked
 * Jev topic folders and whether they split by price. All of them go into ONE apply payload and must match the preview the operator saw (the server re-derives the plan and retires
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
  /** Ticked topic slugs (`service/vault_topic_folders.py`), sorted so the preview's query key and the apply body
   *  never differ by order. None by default: the build is unchanged until the operator opts in. */
  topics: string[];
  /** Topic folders split by price (`AI-bikini free`, `AI-bikini $10`, …); off = one `AI-<topic>` folder each. */
  split: boolean;
}

export type Action =
  | { type: "keep"; keep: number }
  | { type: "solo"; on: boolean }
  | { type: "mirror"; on: boolean }
  | { type: "split"; on: boolean }
  | { type: "topic"; slug: string; on: boolean }
  /** "Select all": every topic the plan offered (`slugs` = its catalogue). */
  | { type: "topicsAll"; slugs: readonly string[] }
  | { type: "topicsNone" };

export const INITIAL_FORM: AiFoldersForm = { keep: 10, solo: false, mirrorToOf: true, topics: [], split: true };

function withTopics(state: AiFoldersForm, next: Iterable<string>): AiFoldersForm {
  const topics = [...new Set(next)].sort();
  const same = topics.length === state.topics.length && topics.every((t, i) => t === state.topics[i]);
  return same ? state : { ...state, topics };
}

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
    case "split":
      return action.on === state.split ? state : { ...state, split: action.on };
    case "topic":
      return withTopics(state, action.on ? [...state.topics, action.slug]
        : state.topics.filter((t) => t !== action.slug));
    case "topicsAll":
      return withTopics(state, action.slugs);
    case "topicsNone":
      return withTopics(state, []);
  }
}

/** The apply call's options: exactly the preview's. */
export function buildPayload(form: AiFoldersForm): {
  keep: number; solo: boolean; mirrorToOf: boolean; topics: string[]; split: boolean;
} {
  return { keep: form.keep, solo: form.solo, mirrorToOf: form.mirrorToOf, topics: form.topics, split: form.split };
}

/** Topic checkboxes are live only when Jev is on for the account AND some item carries its answers. */
export function topicsUsable(jev: { enabled: boolean; with_jev: number } | null | undefined): boolean {
  return !!jev && jev.enabled && jev.with_jev > 0;
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
