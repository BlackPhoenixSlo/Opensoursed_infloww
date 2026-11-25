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
      const prev = state.applied;
      const fresh: Values = { nick: action.nick, notes: action.notes, tags: action.tags };
      // Only untouched fields adopt the fresh value: a late OF read must not clobber an in-progress edit.
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

// Once the live OF query resolves it wins over the chat-list payload (can be hours stale), even if empty.
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

function sameList(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  const A = a.slice().sort();
  const B = b.slice().sort();
  return A.every((v, i) => v === B[i]);
}

export function nickPatch(nick: string, saved: string): { custom_nickname: string | null } | null {
  const next = nick.trim();
  if (next === saved.trim()) return null;
  return { custom_nickname: next || null };
}

export function notesPatch(notes: string, saved: string): { notes: string | null } | null {
  if (notes === saved) return null;
  return { notes: notes || null };
}

export function tagsPatch(tagsInput: string, saved: string[]): { tags: string[] } | null {
  const next = tagsInput
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  if (sameList(next, saved)) return null;
  return { tags: next };
}
