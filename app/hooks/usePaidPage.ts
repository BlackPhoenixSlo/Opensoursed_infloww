"use client";


import { useAccountProfile } from "@/hooks/useStats";

export function usePaidPage(accountId: string | null | undefined) {
  const q = useAccountProfile(accountId);
  // subscribePrice is ground truth (the server gate reads it); paidFeed disagrees with itself across live pages.
  const price = q.data?.subscribePrice;
  const known = typeof price === "number";
  return {
    isPaidPage: known && price > 0,
    subscribePrice: known ? price : null,
    isLoading: q.isLoading,
  };
}

export const PAID_PAGE_NOTE =
  "This page charges for a subscription — OF has no paid-post lane for it. " +
  "Post free, or sell it as a PPV in DMs.";

export function useFreePageRefusal(accountId: string | null | undefined): string | null {
  const { subscribePrice } = usePaidPage(accountId);
  const name = useAccountProfile(accountId).data?.name;
  return subscribePrice === 0
    ? `${name || "This Creator"} is a free subscription profile and is unable to create this message`
    : null;
}
