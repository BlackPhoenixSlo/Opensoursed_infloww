/**
 * The tab strips a URL can open (`?tab=`), as data. Each page draws
 * its strip from here, and components/assistant/answerLinks.ts resolves the
 * help bot's "Page → Tab" paths from the same arrays, so a renamed tab moves
 * both. Data only: the widget imports this, and importing a page component
 * would drag its hooks into the widget's bundle.
 */

// The one import is data too: the captured labels the page test checks against
// the capture file.
import { SM } from "@/components/growth/smartMessagesControls";

export type MessageDashboardTab = "direct" | "mass" | "ppv" | "tips" | "all" | "posts" | "myfeed" | "top" | "customs";

/** app/analytics/message-dashboard/page.tsx: the strip, in order (`?tab=`). */
export const MESSAGE_DASHBOARD_TABS: Array<{ key: MessageDashboardTab; label: string }> = [
  { key: "direct",  label: "Direct messages" },
  { key: "mass",    label: "OnlyFans mass messages" },
  { key: "ppv",     label: "PPV"       },
  { key: "tips",    label: "Tips"      },
  { key: "all",     label: "All"       },
  { key: "customs", label: "Customs"   },
  { key: "posts",   label: "Posts"     },
  { key: "myfeed",  label: "My Feed"   },
  { key: "top",     label: "Top Posts" },
];

export type SmartMessagesTab = "automated" | "mass";

/** components/growth/SmartMessagesPage.tsx: its two tabs (`?tab=`), labelled by the captured controls. */
export const SMART_MESSAGES_TABS: Array<{ key: SmartMessagesTab; label: string }> = [
  { key: "automated", label: SM.tabAutomated.label },
  { key: "mass", label: SM.tabMass.label },
];
