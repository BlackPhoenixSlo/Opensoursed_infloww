/** The earnings channels' icons and colours, one map for the Dashboard header's tiles and Creator reports' Earnings
 *  summary alike (#5). */
import { BookmarkPlus, FileText, Lightbulb, MessageCircleMore, Undo2, UserStar, type LucideIcon } from "lucide-react";

export type Channel = "subscriptions" | "tips" | "posts" | "referrals" | "messages" | "chargebacks";

/**
 * Each channel's icon (capture #58-#63): the glyph 22px in the channel colour on a 45px circle of that colour at 10%
 * over the card (16-dashboard.png samples: Subscriptions #2d3734, Tips #292d3b, Referrals #3a302e, Messages #362d3b,
 * Streams #262a36; Chargebacks, ours, is the err token). `rgb` is "r, g, b".
 */
export const TILE_ICON: Record<Channel, { Icon: LucideIcon; rgb: string }> = {
  subscriptions: { Icon: BookmarkPlus, rgb: "42, 212, 172" },
  tips: { Icon: Lightbulb, rgb: "52, 103, 255" },
  posts: { Icon: FileText, rgb: "42, 212, 172" },
  referrals: { Icon: UserStar, rgb: "255, 124, 113" },
  messages: { Icon: MessageCircleMore, rgb: "206, 99, 255" },
  chargebacks: { Icon: Undo2, rgb: "255, 124, 113" },
};
