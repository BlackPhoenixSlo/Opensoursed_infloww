"use client";

/**
 * Whether a composer for `accountId` may author OF rich text (bold, italic, OF's colours and sizes): only an OnlyFans
 * account. Fansly never gets OF markup (its scripts render as literal text in Infloww too, docs/infloww-rich-text-rea.md
 * §3), so there the "Aa" button and the toolbar are gone and a formatted script goes in as its plain text.
 * The account's platform comes from the owner's cached account list (useAccounts' entry; read only, never fetched
 * here, so a provider-less host still renders); an account not in it (a chatter's platform-less grant, a cold cache)
 * reads as the sidebar platform's (lib/platform), whose account lists hold only that platform's accounts anyway.
 */
import { useQuery } from "@tanstack/react-query";
import { useOptionalUser } from "@/contexts/UserContext";
import { ownerAccountsQuery, type AccountsResp } from "@/hooks/useAccounts";
import { accountPlatform, usePlatform } from "@/lib/platform";

export function useOfRichAllowed(accountId: string | null | undefined): boolean {
  const platform = usePlatform();
  const user = useOptionalUser()?.user;
  const cached = useQuery<AccountsResp>({
    // useAccounts' entry and fetcher (a refetch another reader triggers must find a queryFn), never fetched from here.
    ...ownerAccountsQuery(user?.user_id), enabled: false,
  }).data;
  const a = accountId ? cached?.accounts?.find((x) => x.id === accountId) : undefined;
  return (a ? accountPlatform(a) : platform) === "onlyfans";
}
