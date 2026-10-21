"use client";

/**
 * /messages-pro — Infloww's "Messages Pro" (was /inbox, which redirects here).
 *
 * The whole screen lives in `MessagesPro` (ADR-0002: one tree that the index
 * page renders now, and the Pop-out window and the Deep link are to render too).
 */

import { MessagesPro } from "@/components/chat/MessagesPro";

export default function MessagesProPage() {
  return <MessagesPro />;
}
