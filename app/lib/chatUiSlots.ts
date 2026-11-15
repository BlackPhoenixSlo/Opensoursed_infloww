/**
 * The plugin slots that are components (lib/chatSlots.ts header): read from
 * each plugin's `ui.ts`, through a barrel of their own, so lib/nav.ts
 * (chatSlots' reader, on every page) never loads a plugin's components.
 */
import type { ComponentType } from "react";

import { PLUGINS } from "@/lib/plugins.generated.ui";

export interface ChatUiPlugin {
  /** MessagesPro: buttons at the Window header's right end, before Notif and SFW. */
  windowHeaderActions?: readonly ComponentType[];
}

export const WINDOW_HEADER_ACTIONS: readonly ComponentType[] = PLUGINS.flatMap((p) => p.windowHeaderActions ?? []);
