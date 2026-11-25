import type { ChatPlugin } from "@/lib/chatSlots";
import type { ChatUiPlugin } from "@/lib/chatUiSlots";

export const PLUGINS: readonly (ChatPlugin & ChatUiPlugin)[] = [];
