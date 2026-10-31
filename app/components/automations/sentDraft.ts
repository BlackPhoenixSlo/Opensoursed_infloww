/**
 * A form's draft plus the draft its last Save sent, for the automation pages (Auto-reply, Get to know fans).
 *
 *   • `withSent(edit)` turns a form's pure edit fn into its reducer: an edit replaces the draft, `saved` (Save sent
 *     the draft as it is now) records it as sent.
 *   • The edit fn returns a new draft every time, so `unsaved` (draft !== sent) holds "Saved" off over an edit made
 *     while that save was in flight, even one back to the sent value.
 */

export interface SentState<D> {
  draft: D;
  /** The draft the last Save sent; null before one. */
  sent: D | null;
}

/** Save sent the draft as it is now. */
export type Saved = { type: "saved" };

/** The state for a freshly seeded draft: nothing sent yet. */
export const sentState = <D>(draft: D): SentState<D> => ({ draft, sent: null });

/** An edit since the last Save (or no Save yet): "Saved" stays off. */
export const unsaved = <D>(s: SentState<D>) => s.draft !== s.sent;

const isSaved = <E extends { type: string }>(a: E | Saved): a is Saved => a.type === "saved";

export function withSent<D, E extends { type: string }>(edit: (d: D, e: E) => D) {
  return (s: SentState<D>, a: E | Saved): SentState<D> =>
    isSaved(a) ? { ...s, sent: s.draft } : { ...s, draft: edit(s.draft, a) };
}
