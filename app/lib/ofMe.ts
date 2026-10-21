"use client";

/**
 * The Creator's own OnlyFans user (`/users/me`): its type and the one query
 * every reader shares (one cache entry and request per Creator): the OF
 * mirror (ofMirrorIdentity re-exports both), Growth and Messages Pro's Fan List.
 */

import { relay } from "@/lib/relay";

export interface OfMe {
  /** The Creator's OnlyFans user id (My profile's posts are read by it). */
  id?: number | string;
  username?: string | null;
  name?: string | null;
  avatar?: string | null;
  header?: string | null;
  subscribePrice?: number | null;
  /** OF's own source of the Subscription page's bundle list (authUser.subscriptionBundles). */
  subscriptionBundles?: { id?: number | string; price?: number | null; duration?: number | null; discount?: number | null }[] | null;
  /** OF's own source of the Subscription page's promotion list (user.promotions; absent while the price is free). */
  promotions?: { id?: number | string; type?: string | null; hasRelatedPromo?: boolean }[] | null;
  /** Without it OF grays the Subscription page's promotion header. */
  canCreatePromotion?: boolean;
  /** OF's other create gates on the Subscription pages: Start promotion campaign (isPerformer) and the free trial links (canCreateTrial). */
  isPerformer?: boolean;
  canCreateTrial?: boolean;
  /** New post's price button (OF's isShowPriceBtn) and its POST PRICE limits. */
  canChangeContentPrice?: boolean;
  canEarn?: boolean;
  postMinPrice?: number | null;
  postMaxPrice?: number | null;
  /** The Notifications page's Tags tab count. */
  newTagsCount?: number;
  /** The left nav's counts (the generator marks each with data-oi-count): Notifications and Chats badges, Fans, Following. */
  notificationsCount?: number | null;
  chatMessagesCount?: number | null;
  subscribersCount?: number | null;
  subscribesCount?: number | null;
  rawAbout?: string | null;
  about?: string | null;
  /** The avatar menu's own rows, by OF's sidebar rules: the name's verified badge, the avatar's online dot, and
   *  the bank row (OF's dropdown_menu_item_bank "Bank (to earn)" for a model that can be paid out, else the capture's "Add bank (to earn)"). */
  isVerified?: boolean;
  isVisibleOnline?: boolean;
  canReceiveManualPayout?: boolean;
  /** Tips are on for the Creator: OF offers its chats list's "Unread with tips" only then. */
  tipsEnabled?: boolean | null;
}

/** The "who am I" query (`/users/me`) for one Creator: every reader shares its one cache entry and request. */
export const ofMeQuery = (accountId: string | null) => ({
  queryKey: ["of-me", accountId],
  queryFn: () => relay.get<OfMe>("/api/of/v2/users/me", { accountId }),
  enabled: !!accountId,
  staleTime: 5 * 60 * 1000,
  retry: false,
});
