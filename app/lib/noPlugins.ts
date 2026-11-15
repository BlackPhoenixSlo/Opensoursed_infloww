/** tsc's stand-in for the gitignored `lib/plugins.generated.register.ts` and
 *  `lib/plugins.generated.ui.ts` before anything wrote them (tsconfig
 *  `paths`; lib/chatSlots.ts): one empty list for both barrels' types. Both
 *  barrels carry a suffix after `plugins.generated`: webpack's (`next dev
 *  --webpack`) paths plugin leaves the `*` in when it matches nothing, so a
 *  bare `plugins.generated` landed here and every slot was empty (SWC rejects
 *  an exact key with a fallback). */
import type { ChatPlugin } from "@/lib/chatSlots";
import type { ChatUiPlugin } from "@/lib/chatUiSlots";

export const PLUGINS: readonly (ChatPlugin & ChatUiPlugin)[] = [];
