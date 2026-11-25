import type { ComponentType } from "react";

import { PLUGINS } from "@/lib/plugins.generated.ui";

export interface ChatUiPlugin {
  windowHeaderActions?: readonly ComponentType[];
}

export const WINDOW_HEADER_ACTIONS: readonly ComponentType[] = PLUGINS.flatMap((p) => p.windowHeaderActions ?? []);
