import type { OFMessage } from "@/lib/relay";
import type { AttributionEntry } from "@/hooks/useChatAttribution";
import { MASS_PLACEHOLDER_MIN } from "@/hooks/useChatMessages";
import { toUtcIso } from "@/hooks/useInboxRealtime";

/** One "Message withdrawn" line (roadmap W4 4.11): an unsend WE made, which
 *  our DB recorded (`messages.unsent_at`, read off the attribution map). OF's
 *  own unsend push is unknown, so a Fan's or an OF-web unsend draws nothing. */
export interface WithdrawnLine {
  id: number;
  /** When the withdrawn message was sent (UTC ISO), for its Date divider. */
  createdAt?: string;
  /** An automation pulled it ("automation:…" reason), not a chatter. */
  auto: boolean;
  /** Draw it before `messages[before]`, the first newer message, or at the
   *  end when it is `messages.length`. */
  before: number;
}

/** The withdrawn lines for the loaded thread, in id order. The attribution
 *  map only reaches back to the oldest loaded message (its `since_id`), so a
 *  line never stands above messages not yet loaded. Ids from the
 *  mass-placeholder band up are our own stand-ins and ledger rows, not OF
 *  messages, so they neither draw nor place a line. The server sends
 *  `created_at` zone-less (naive UTC), so it is tagged UTC before any
 *  local-day comparison. */
export function withdrawnLines(
  messages: OFMessage[], attribution: Record<string, AttributionEntry> | null | undefined,
): WithdrawnLine[] {
  const ofId = (m: OFMessage) => {
    const n = Number(m.id);
    return n > 0 && n < MASS_PLACEHOLDER_MIN ? n : null;
  };
  const shown = new Set(messages.map((m) => String(m.id)));
  return Object.entries(attribution ?? {})
    .map(([key, e]) => ({ key, id: Number(key), e }))
    .filter(({ key, id, e }) => e.unsent_at && !shown.has(key) && id > 0 && id < MASS_PLACEHOLDER_MIN)
    .sort((a, b) => a.id - b.id)
    .map(({ id, e }) => {
      const at = messages.findIndex((m) => (ofId(m) ?? 0) > id);
      return {
        id, createdAt: e.created_at ? toUtcIso(e.created_at) : undefined,
        auto: (e.unsent_reason ?? "").startsWith("automation:"),
        before: at < 0 ? messages.length : at,
      };
    });
}
