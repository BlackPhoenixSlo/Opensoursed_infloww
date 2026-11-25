export interface SentState<D> {
  draft: D;
  sent: D | null;
}

export type Saved = { type: "saved" };

export const sentState = <D>(draft: D): SentState<D> => ({ draft, sent: null });

// The edit fn returns a new draft each time, so an edit made while a save is in flight keeps "Saved" off.
export const unsaved = <D>(s: SentState<D>) => s.draft !== s.sent;

const isSaved = <E extends { type: string }>(a: E | Saved): a is Saved => a.type === "saved";

export function withSent<D, E extends { type: string }>(edit: (d: D, e: E) => D) {
  return (s: SentState<D>, a: E | Saved): SentState<D> =>
    isSaved(a) ? { ...s, sent: s.draft } : { ...s, draft: edit(s.draft, a) };
}
