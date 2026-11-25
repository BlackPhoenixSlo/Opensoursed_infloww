import { BookmarkPlus, FileText, Lightbulb, MessageCircleMore, Undo2, UserStar, type LucideIcon } from "lucide-react";

export type Channel = "subscriptions" | "tips" | "posts" | "referrals" | "messages" | "chargebacks";

export const TILE_ICON: Record<Channel, { Icon: LucideIcon; rgb: string }> = {
  subscriptions: { Icon: BookmarkPlus, rgb: "42, 212, 172" },
  tips: { Icon: Lightbulb, rgb: "52, 103, 255" },
  posts: { Icon: FileText, rgb: "42, 212, 172" },
  referrals: { Icon: UserStar, rgb: "255, 124, 113" },
  messages: { Icon: MessageCircleMore, rgb: "206, 99, 255" },
  chargebacks: { Icon: Undo2, rgb: "255, 124, 113" },
};
