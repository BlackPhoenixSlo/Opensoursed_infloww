"use client";


import { relay } from "@/lib/relay";

export interface OfMe {
  id?: number | string;
  username?: string | null;
  name?: string | null;
  avatar?: string | null;
  header?: string | null;
  subscribePrice?: number | null;
  subscriptionBundles?: { id?: number | string; price?: number | null; duration?: number | null; discount?: number | null }[] | null;
  promotions?: { id?: number | string; type?: string | null; hasRelatedPromo?: boolean }[] | null;
  canCreatePromotion?: boolean;
  isPerformer?: boolean;
  canCreateTrial?: boolean;
  canChangeContentPrice?: boolean;
  canEarn?: boolean;
  postMinPrice?: number | null;
  postMaxPrice?: number | null;
  newTagsCount?: number;
  notificationsCount?: number | null;
  chatMessagesCount?: number | null;
  subscribersCount?: number | null;
  subscribesCount?: number | null;
  rawAbout?: string | null;
  about?: string | null;
  location?: string | null;
  website?: string | null;
  wishlist?: string | null;
  isVerified?: boolean;
  isVisibleOnline?: boolean;
  canReceiveManualPayout?: boolean;
  tipsEnabled?: boolean | null;
}

export const ofMeQuery = (accountId: string | null) => ({
  queryKey: ["of-me", accountId],
  queryFn: ({ signal }: { signal?: AbortSignal }) =>
    relay.get<OfMe>("/api/of/v2/users/me", { accountId, priority: "background" }, signal),
  enabled: !!accountId,
  staleTime: 5 * 60 * 1000,
  retry: false,
});
