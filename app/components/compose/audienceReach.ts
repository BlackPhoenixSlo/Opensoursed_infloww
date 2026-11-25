import { SYSTEM_AUDIENCES, type FanList } from "@/components/audience/fanLists";

import type { MassForm } from "./massMessageReducer";

type ReachForm = Pick<MassForm, "allModels" | "includes" | "excludes" | "smartInclude" | "smartExclude">;

// upper bound only: OF dedupes a fan in two included lists, Smart Lists / excluded lists resolve on send
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
  if (upTo === 0) return hasSystem ? "Reach: system audience" : null;
  return `Reach: up to ${upTo} fan${upTo === 1 ? "" : "s"} from custom lists${hasSystem ? " + system audience" : ""}`;
}
