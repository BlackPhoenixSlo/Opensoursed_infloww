"use client";


import { AssistantPanel } from "./AssistantWidget";

// help.infloww.com sends x-frame-options: DENY, so Infloww's frame holds our help bot instead.
export default function HelpCenterPage() {
  return <AssistantPanel variant="page" />;
}
