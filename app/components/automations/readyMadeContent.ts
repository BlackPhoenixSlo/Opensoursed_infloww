/**
 * readyMadeContent — the ready-made rule's words and its one content gate, pure
 * (ReadyMadePanel, ReadyMadeRuleEditor, ComposeModal only read these).
 *
 *   • `KIND_COPY` — the words each kind is shown with.
 *   • `hasContent` — the kind's own list (premadeRows `listItems`) has at least one entry (any entry counts).
 *   • `summarize` — the compose read-out line; `null` when that list is empty.
 *   • `canSave` — Create / Save changes is live: the raw buffer parses (`canSubmit`) and `hasContent`.
 */

import { listItems, type Kind } from "@/components/compose/premadeRows";
import { canSubmit, type RawJsonState } from "@/lib/rawJsonReducer";
import type { Payload } from "@/lib/rulePayload";

/** The words each rule kind is shown with. Auto Mass sends OF mass messages
 *  (`mass_premade` delegates to `send_mass_message`, OF's messages/queue), so
 *  its copy uses Infloww's names: "mass message", "Auto-unsend". */
export const KIND_COPY: Record<Kind, {
  /** The page title when the panel is pinned to this kind (`only`). */
  title: string;
  /** Learn's popover text when pinned. */
  blurb: string;
  /** The pinned header's primary. */
  button: string;
  /** "New …" (the editor's title). */
  noun: string;
  /** "No … yet" (the empty table). */
  plural: string;
  /** One item of the payload list, and the list's label. */
  item: string;
  items: string;
  /** The Name field's placeholder. */
  namePlaceholder: string;
  /** "nothing is …" (Dry run's help). */
  pastVerb: string;
  /** The compose dialog's title. */
  composeTitle: string;
}> = {
  auto_posts: {
    title: "Auto Post",
    button: "New auto post",
    blurb:
      "Posts that publish on their own schedule, one at a time, and can delete " +
      "themselves after the hours you set. See what's queued next and the recent " +
      "runs below. “Run now” posts the next one immediately.",
    noun: "auto post",
    plural: "auto posts",
    item: "post",
    items: "Posts",
    namePlaceholder: "Auto posts",
    pastVerb: "posted",
    composeTitle: "Compose auto posts",
  },
  mass_premade: {
    title: "Auto Mass",
    button: "New auto mass",
    blurb:
      "Mass messages that send on their own schedule to the fans you pick, " +
      "through the same OF mass message path as Smart Messages (sent to the " +
      "general inbox). Each message can be resent on a timer and unsent " +
      "automatically after the hours you set. See what's queued next and the " +
      "recent runs below. “Run now” sends it immediately.",
    noun: "auto mass message",
    plural: "auto mass messages",
    item: "message",
    items: "Messages",
    namePlaceholder: "Auto mass",
    pastVerb: "sent",
    composeTitle: "Compose premade mass",
  },
};

/** The kind's own list in `payload` has at least one entry (any entry counts). */
export function hasContent(payload: Payload, kind: Kind): boolean {
  return listItems(payload, kind).length > 0;
}

/** One-line summary of the kind's list for the compose read-out: "3 posts · reposts ×2 · first caption…".
 *  `null` = that list is empty. */
export function summarize(payload: Payload, kind: Kind): string | null {
  const arr = listItems(payload, kind);
  if (arr.length === 0) return null;
  const noun = KIND_COPY[kind].item;
  const bits = [`${arr.length} ${noun}${arr.length === 1 ? "" : "s"}`];
  const rc = payload.resend_count;
  if (typeof rc === "number" && rc > 0) bits.push(`reposts ×${rc}`);
  const first = arr[0] as { text?: unknown; texts?: unknown } | undefined;
  const text = typeof first?.text === "string" ? first.text
    : Array.isArray(first?.texts) && typeof first.texts[0] === "string" ? first.texts[0] : "";
  if (text.trim()) bits.push(text.trim());
  return bits.join(" · ");
}

/** Create / Save changes is live: the raw buffer parses and the kind's list is not empty. */
export function canSave(raw: RawJsonState<Payload>, kind: Kind): boolean {
  return canSubmit(raw) && hasContent(raw.value, kind);
}
