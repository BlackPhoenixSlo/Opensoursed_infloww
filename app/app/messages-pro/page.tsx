"use client";


import { MessagesPro } from "@/components/chat/MessagesPro";
import { useScope } from "@/contexts/ScopeContext";
import { useScreen } from "@/lib/screenBundle";
import type { Screen } from "@/lib/screenKey";

const INBOX: Screen = { kind: "inbox", cursor: 0 };

export default function MessagesProPage() {
  useScreen(useScope().accountId == null ? INBOX : null);
  return <MessagesPro />;
}
