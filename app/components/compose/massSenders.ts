import { accountPlatform, can, type Platform } from "@/lib/platform";
import type { AccountMeta } from "@/lib/relay";

export function massSenders<A extends Pick<AccountMeta, "platform">>(accounts: readonly A[], platform: Platform): A[] {
  if (!can(platform, "mass_message")) return [];
  return accounts.filter((a) => accountPlatform(a) === platform);
}
