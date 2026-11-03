/**
 * The Fan insights drawer's editable form: the local mirrors of Nickname,
 * Notes and Tags, the values last pushed into them, and the OF write-through
 * error. A pure reducer (FanDrawer only dispatches), `effectiveFields` (the
 * values it adopts) and `nickPatch` / `notesPatch` / `tagsPatch`, the save
 * each field's blur makes (or none).
 *
 * Local form mirrors so blur-save doesn't fight the cache when the user is
 * mid-edit. `applied` holds the values we last pushed into the form mirrors.
 * A field is "dirty" (being edited) when its current value no longer equals
 * what we applied — in that case a fresh OF value must NOT overwrite it.
 *
 * The OF write-through (custom name / private note) is fire-and-forget and
 * hits a different backend than the local PATCH. When it rejects the local
 * mirror still updates, so without `ofWriteError` the panel shows a value OF
 * never accepted and silently reverts the next time of-user is re-read.
 * Surface the failure so the operator knows the OF sync didn't stick.
 */

export type FormField = "nick" | "notes" | "tags";
type Values = Record<FormField, string>;

export interface FanDrawerForm extends Values {
  applied: Values;
  ofWriteError: string | null;
}

export type Action =
  | { type: "adopt"; nick: string; notes: string; tags: string }
  | { type: "edit"; field: FormField; value: string }
  | { type: "ofWriteFailed"; field: "nick" | "notes" }
  | { type: "clearError" };

export const INITIAL_FORM: FanDrawerForm = {
  nick: "", notes: "", tags: "",
  applied: { nick: "", notes: "", tags: "" },
  ofWriteError: null,
};

const OF_WRITE_ERROR: Record<"nick" | "notes", string> = {
  nick: "Saved locally, but OnlyFans rejected the nickname change — it may revert on the next sync.",
  notes: "Saved locally, but OnlyFans rejected the note change — it may revert on the next sync.",
};

export function fanDrawerFormReducer(state: FanDrawerForm, action: Action): FanDrawerForm {
  switch (action.type) {
    case "adopt": {
      // Adopt the freshest effective value ONLY for fields the user hasn't touched.
      // A fresh OF read can land at any time (focus refetch, an invalidation, or
      // the pre-edit refresh), and a naive reset would clobber an in-progress
      // edit; comparing against the last-applied value keeps the operator's
      // typing while still picking up out-of-band changes. `applied` takes the
      // fresh values either way.
      const prev = state.applied;
      const fresh: Values = { nick: action.nick, notes: action.notes, tags: action.tags };
      const next: Values = {
        nick: state.nick === prev.nick ? fresh.nick : state.nick,
        notes: state.notes === prev.notes ? fresh.notes : state.notes,
        tags: state.tags === prev.tags ? fresh.tags : state.tags,
      };
      const same = (a: Values, b: Values) => a.nick === b.nick && a.notes === b.notes && a.tags === b.tags;
      if (same(next, state) && same(fresh, prev)) return state;
      return { ...state, ...next, applied: fresh };
    }
    case "edit":
      return { ...state, [action.field]: action.value };
    case "ofWriteFailed":
      return { ...state, ofWriteError: OF_WRITE_ERROR[action.field] };
    case "clearError":
      return state.ofWriteError === null ? state : { ...state, ofWriteError: null };
  }
}

/** The "effective" nickname/note, with OF as the authoritative read (it's what
 *  shows on onlyfans.com). ONCE the live OF query has resolved we trust IT — even
 *  an empty value — over the chat-list payload, because that payload can be hours
 *  stale and would otherwise pin an out-of-date nickname/note after an automation
 *  (or another device) changed it. Before the OF query lands we fall back to the
 *  chat-list value for an instant first paint, then our local SQLite mirror so the
 *  panel never blanks when OF is slow/unreachable. On blur we write through to OF
 *  AND our local row so the two stay in sync. */
export function effectiveFields(
  ofUserQ: { isSuccess: boolean; data?: { displayName?: string | null; notice?: string | null } | null },
  withUser: { displayName?: string | null; notice?: string | null },
  fan: { custom_nickname?: string | null; notes?: string | null } | null | undefined,
): { effectiveNickname: string; effectiveNotes: string } {
  const ofDisplayName = ofUserQ.isSuccess
    ? (ofUserQ.data?.displayName ?? "")
    : (withUser.displayName ?? "");
  const ofNotice = ofUserQ.isSuccess
    ? (ofUserQ.data?.notice ?? "")
    : (withUser.notice ?? "");
  const effectiveNickname = ofDisplayName || fan?.custom_nickname || "";
  const effectiveNotes = ofNotice || fan?.notes || "";
  return { effectiveNickname, effectiveNotes };
}

/** Tags compare order-insensitively: same length, same members once sorted. */
function sameList(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const A = a.slice().sort();
  const B = b.slice().sort();
  return A.every((v, i) => v === B[i]);
}

/** Nickname's blur save, or null when unchanged: compares trimmed. */
export function nickPatch(nick: string, saved: string): { custom_nickname: string | null } | null {
  const next = nick.trim();
  if (next === saved.trim()) return null;
  return { custom_nickname: next || null };
}

/** Notes' blur save, or null when unchanged: compares exactly (untrimmed). */
export function notesPatch(notes: string, saved: string): { notes: string | null } | null {
  if (notes === saved) return null;
  return { notes: notes || null };
}

/** Tags' blur save, or null when unchanged: the comma list, trimmed, empties
 *  dropped, compared order-insensitively. */
export function tagsPatch(tagsInput: string, saved: string[]): { tags: string[] } | null {
  const next = tagsInput
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  if (sameList(next, saved)) return null;
  return { tags: next };
}
