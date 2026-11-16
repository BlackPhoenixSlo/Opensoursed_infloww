"use client";

import { useQuery } from "@tanstack/react-query";

import { relay } from "@/lib/relay";

const categoryNames: Record<string, string> = {
  "bare booty": "bare-booty",
  "ass - bare": "bare-booty",
  "bikini and lingerie booty": "bikini-lingerie",
  "covered booty (clothed)": "covered-booty",
  "ass - covered": "covered-booty",
  "covered breast content": "covered-breast",
  "bare breast": "bare-breast",
  "bare breast content": "bare-breast",
  "feet photos": "feet",
  "feet": "feet",
  "handbra": "handbra",
  "long videos and livestream replays": "long-videos",
  "customs": "customs",
};

function categoryLabel(name: string): string {
  return (name.split(" / ").at(-1) ?? name).replace(/^[\p{Extended_Pictographic}\uFE0F]+\s*/u, "");
}

export function folderIconCategory(name: string): string | undefined {
  const label = categoryLabel(name).toLowerCase();
  return Object.hasOwn(categoryNames, label) ? categoryNames[label] : undefined;
}

export function folderNameWithoutEmoji(name: string): string {
  const label = categoryLabel(name);
  const split = name.lastIndexOf(" / ");
  return split === -1 ? label : name.slice(0, split + 3) + label;
}

export function categoryIconsPath(accountId: string, category?: string): string {
  const tail = category ? "/" + encodeURIComponent(category) : "";
  return "/admin/vault-ai/category-icons" + tail + "?account_id=" + encodeURIComponent(accountId);
}

export const categoryIconsKey = (accountId: string) => ["vault-category-icons", accountId] as const;

export function useVaultCategoryIcons(accountId: string, enabled: boolean) {
  return useQuery({
    queryKey: categoryIconsKey(accountId),
    queryFn: ({ signal }) => relay.get<{ can_edit: boolean; icons: Record<string, string> }>(
      categoryIconsPath(accountId), { accountId }, signal,
    ),
    enabled,
    staleTime: 30_000,
    gcTime: 0,
    retry: false,
    meta: { persist: false },
  });
}
