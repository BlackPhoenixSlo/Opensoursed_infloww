/**
 * readyMadeContent — the ready-made rule's words and content checks, pure
 * (ReadyMadePanel and ReadyMadeRuleEditor only read these).
 *
 *   • `KIND_COPY` — the words each kind is shown with.
 *   • `hasContent` — the kind's own list (premadeRows `listItems`) has at least one entry (any entry counts).
 *   • `summarize` — the compose read-out line; `null` when that list is empty.
 *   • `isLegacy` — an older multi-item / resend / delayed payload the one-item Composer can't hold (it keeps
 *     running; the editor sends it to Raw JSON).
 */

import { listItems, type Kind } from "@/components/compose/premadeRows";
import type { Payload } from "@/lib/rulePayload";
import { fmtPrice } from "@/lib/format";

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
}> = {
  auto_posts: {
    title: "Auto Post",
    button: "New auto post",
    blurb:
      "One post per rule, published each time the rule runs. It can delete " +
      "itself after the hours you set. Another post on another schedule is " +
      "another rule. See what's queued next and the recent runs below. " +
      "“Run now” posts it immediately.",
    noun: "auto post",
    plural: "auto posts",
    item: "post",
    items: "Post",
    namePlaceholder: "Auto post",
    pastVerb: "posted",
  },
  mass_premade: {
    title: "Auto Mass",
    button: "New auto mass",
    blurb:
      "One mass message per rule, sent each time the rule runs to the fans you " +
      "pick. Choose who gets it with audience and recent-chat rules. It uses the " +
      "same OF mass message path as Smart Messages (sent to the general inbox). " +
      "It can unsend itself after the hours you set. Another " +
      "message on another schedule is another rule. See what's queued next and " +
      "the recent runs below. “Run now” sends it immediately.",
    noun: "auto mass message",
    plural: "auto mass messages",
    item: "message",
    items: "Message",
    namePlaceholder: "Auto mass",
    pastVerb: "sent",
  },
};

/** The kind's own list in `payload` has at least one entry (any entry counts). */
export function hasContent(payload: Payload, kind: Kind): boolean {
  return listItems(payload, kind).length > 0;
}

/** One-line summary of the kind's list for the compose read-out: one item reads "Free · caption" /
 *  "$12 · caption" (a post adds "· deletes after 6h"); a legacy list "3 posts · reposts ×2 · first caption…".
 *  `null` = that list is empty. */
export function summarize(payload: Payload, kind: Kind): string | null {
  const arr = listItems(payload, kind);
  if (arr.length === 0) return null;
  const noun = KIND_COPY[kind].item;
  const first = arr[0] as { text?: unknown; texts?: unknown; price?: unknown; hours_to_live?: unknown;
    user_lists?: unknown; online_only?: unknown; exclude_last_chat_hours?: unknown } | null | undefined;
  const bits = arr.length === 1
    ? [typeof first?.price === "number" && first.price > 0 ? fmtPrice(Math.round(first.price * 100)) : "Free"]
    : [`${arr.length} ${noun}s`];
  const rc = payload.resend_count;
  if (typeof rc === "number" && rc > 0) bits.push(`reposts ×${rc}`);
  const text = typeof first?.text === "string" ? first.text
    : Array.isArray(first?.texts) && typeof first.texts[0] === "string" ? first.texts[0] : "";
  if (text.trim()) bits.push(text.trim());
  if (kind === "mass_premade") {
    const lists = Array.isArray(first?.user_lists) ? first.user_lists.map(String) : [];
    const audience: string[] = [];
    if (lists.includes("fans")) audience.push("Fans");
    else if (lists.includes("following")) audience.push("Following");
    if (lists.some((id) => id !== "fans" && id !== "following")) audience.push("Lists");
    if (first?.online_only === true) audience.push("Online");
    if (audience.length) bits.push(audience.join(" + "));
    const skip = Number(first?.exclude_last_chat_hours);
    if (Number.isFinite(skip) && skip > 0) bits.push(`skips chatted ${skip}h`);
  }
  const htl = first?.hours_to_live;
  if (kind === "auto_posts" && arr.length === 1 && typeof htl === "number" && htl > 0) bits.push(`deletes after ${htl}h`);
  return bits.join(" · ");
}

/** A payload from before one-rule-one-item: several posts / messages, a resend / delay timer on the one, or (Auto
 *  Post) the list-level repost cycle. It keeps running server-side; the Composer would drop those knobs, so the
 *  editor routes it to Raw JSON. */
export function isLegacy(payload: Payload, kind: Kind): boolean {
  const arr = listItems(payload, kind);
  if (arr.length > 1) return true;
  const timed = (o: Record<string, unknown>) => ["resend_count", "resend_after_hours", "delay_minutes"]
    .some((k) => Number(o[k]) > 0);
  return timed((arr[0] ?? {}) as Record<string, unknown>) || (kind === "auto_posts" && timed(payload));
}
