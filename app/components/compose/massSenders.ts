import { accountPlatform, can, type Platform } from "@/lib/platform";
import type { AccountMeta } from "@/lib/relay";

import { includedTargets } from "./fanOut";
import type { MassForm } from "./massMessageReducer";

export function massSenders<A extends Pick<AccountMeta, "platform">>(accounts: readonly A[], platform: Platform): A[] {
  if (!can(platform, "mass_message")) return [];
  return accounts.filter((a) => accountPlatform(a) === platform);
}

export function massSendFrom(
  form: Pick<MassForm, "platform" | "launch" | "allModels" | "accountId" | "results">,
  roster: readonly Pick<AccountMeta, "id" | "platform">[],
  isIncluded: (id: string) => boolean,
  accountMaySend: boolean,
): string[] {
  if (form.launch !== null && (form.launch === "unknown" || !can(form.launch, "mass_message"))) return [];
  if (!form.allModels) return form.accountId && accountMaySend ? [form.accountId] : [];
  return includedTargets(massSenders(roster, form.platform), isIncluded, form.results).targets;
}
