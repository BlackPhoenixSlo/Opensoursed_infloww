/**
 * The mass composer's "Reach" hint (AudiencePanel). Only an upper bound: OF dedupes a fan who sits in two
 * included lists, and Smart Lists / excluded lists resolve on send, so with either picked no number is shown.
 */
import { SYSTEM_AUDIENCES, type FanList } from "@/components/audience/fanLists";

import type { MassForm } from "./massMessageReducer";

type ReachForm = Pick<MassForm, "allModels" | "includes" | "excludes" | "smartInclude" | "smartExclude">;

/** The hint's text, or null when there is none (all-models mode, or nothing picked). */
export function reachHint(form: ReachForm, customLists: readonly FanList[]): string | null {
  const { allModels, includes, excludes, smartInclude, smartExclude } = form;
  if (allModels) return null;
  if (includes.size + excludes.size + smartInclude.size + smartExclude.size === 0) return null;
  if (excludes.size > 0 || smartInclude.size > 0 || smartExclude.size > 0) {
    return "Reach: counted on send (Smart Lists or excluded lists picked)";
  }
  const ids = Array.from(includes);
  const hasSystem = ids.some((id) => SYSTEM_AUDIENCES.some((b) => b.id === id));
  const custom = ids.filter((id) => !SYSTEM_AUDIENCES.some((b) => b.id === id));
  if (custom.length === 0) return "Reach: system audience";
  const upTo = custom.reduce((sum, id) => sum + (customLists.find((x) => String(x.id) === id)?.usersCount ?? 0), 0);
  // No picked list carries a count: no number beats "up to 0 fans".
  if (upTo === 0) return hasSystem ? "Reach: system audience" : null;
  return `Reach: up to ${upTo} fan${upTo === 1 ? "" : "s"} from custom lists${hasSystem ? " + system audience" : ""}`;
}
