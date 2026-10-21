"use client";

/**
 * /help-center: Infloww's HelpPage frame (white, full bleed, no page header,
 * the full height under the top bar) holding our help, which is the help bot.
 * Infloww's frame holds help.infloww.com, which cannot be framed
 * (x-frame-options: DENY) and is their content, not ours. The panel is the
 * corner messenger's own (AssistantWidget.tsx, `variant="page"`) and reads the
 * same conversation, so the corner launcher hides on this route.
 */

import { AssistantPanel } from "./AssistantWidget";

export default function HelpCenterPage() {
  return <AssistantPanel variant="page" />;
}
