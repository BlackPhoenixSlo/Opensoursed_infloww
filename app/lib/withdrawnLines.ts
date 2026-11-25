import type { OFMessage } from "@/lib/relay";
import type { AttributionEntry } from "@/hooks/useChatAttribution";
import { MASS_PLACEHOLDER_MIN } from "@/hooks/useChatMessages";
import { toUtcIso } from "@/hooks/useInboxRealtime";

export interface WithdrawnLine {
  id: number;
  createdAt?: string;
  auto: boolean;
  before: number;
}

// Only unsends WE made (messages.unsent_at); OF's own unsend push is unknown. The server's created_at is naive UTC, so tag it UTC before any local-day comparison.
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
