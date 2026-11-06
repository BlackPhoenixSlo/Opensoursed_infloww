"use client";

/**
 * /messages-pro — Infloww's "Messages Pro" (was /inbox, which redirects here).
 *
 * The whole screen lives in `MessagesPro` (ADR-0002: one tree that the index
 * page renders now, and the Pop-out window and the Deep link are to render too).
 */

import { MessagesPro } from "@/components/chat/MessagesPro";
import { useScreen } from "@/lib/screenBundle";

const INBOX = { kind: "inbox" } as const;

export default function MessagesProPage() {
  // Every Creator's bell and first chat page in one relay call (lib/screenBundle.ts).
  useScreen(INBOX);
  return <MessagesPro />;
}
