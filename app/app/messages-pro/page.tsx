"use client";

/**
 * /messages-pro — Infloww's "Messages Pro" (was /inbox, which redirects here).
 *
 * The whole screen lives in `MessagesPro` (ADR-0002: one tree that the index
 * page renders now, and the Pop-out window and the Deep link are to render too).
 */

import { MessagesPro } from "@/components/chat/MessagesPro";
import { useScope } from "@/contexts/ScopeContext";
import { useScreen } from "@/lib/screenBundle";
import type { Screen } from "@/lib/screenKey";

const INBOX: Screen = { kind: "inbox", cursor: 0 };

export default function MessagesProPage() {
  // All Models: every Creator's first chat page in one relay call (lib/screenBundle.ts); one Creator: its own reads.
  useScreen(useScope().accountId == null ? INBOX : null);
  return <MessagesPro />;
}
