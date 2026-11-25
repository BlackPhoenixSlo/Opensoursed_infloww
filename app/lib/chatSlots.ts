import type { ComponentType } from "react";

import type { FanId } from "@/lib/fanId";
import type { NavLink } from "@/lib/nav";
// Cycle rule: nothing a plugin's register.ts imports may import a value from this module; slots are read once at load.
import { PLUGINS } from "@/lib/plugins.generated.register";
import type { FanRecord } from "@/lib/relayTypes";

export interface NavLinkSlot {
  group: string;
  link: NavLink;
  first?: boolean;
}

export interface ChatPlugin {
  navLinks?: readonly NavLinkSlot[];
  popoutModeRoutes?: readonly string[];
  scriptSource?: ScriptSourceSlot;
  fanSpendCents?: (fan: FanRecord) => number | null | undefined;
  consentFixHref?: (accountId: string) => string;
  keptStorage?: (key: string) => boolean;
}

export const NAV_LINK_SLOTS: readonly NavLinkSlot[] = PLUGINS.flatMap((p) => p.navLinks ?? []);
export const POPOUT_MODE_ROUTES: ReadonlySet<string> = new Set(PLUGINS.flatMap((p) => p.popoutModeRoutes ?? []));


export interface SourceStep {
  scriptId: string;
  step: number;
  label: string;
  text: string;
}

export interface ScriptSourceSlot {
  owns: (scriptId: string | null | undefined) => boolean;
  searchPrefix: string;
  label: string;
  useSource: (accountId: string | null, fanId: FanId | null, fanSpokeLastAt: string | null) => {
    scriptId: string | null;
    next: SourceStep | null;
    dismiss: () => void;
    skip: (scriptId: string, step: number) => void;
    markSent: (scriptId: string, step: number) => void;
  };
  StepAction?: ComponentType<{ accountId: string; fanId: FanId; replyAt: string | null; onDraft: (text: string) => void }>;
}

export const SCRIPT_SOURCE: ScriptSourceSlot | null = PLUGINS.find((p) => p.scriptSource)?.scriptSource ?? null;

export function isSourceScript(scriptId: string | null | undefined): boolean {
  return !!SCRIPT_SOURCE?.owns(scriptId);
}


export const FAN_SPEND_SOURCES: readonly ((fan: FanRecord) => number | null | undefined)[] =
  PLUGINS.flatMap((p) => (p.fanSpendCents ? [p.fanSpendCents] : []));
export function keptStorage(key: string): boolean {
  return PLUGINS.some((p) => p.keptStorage?.(key));
}
export const CONSENT_FIX_HREF: (accountId: string) => string =
  PLUGINS.find((p) => p.consentFixHref)?.consentFixHref
  ?? ((accountId) => `/settings/consent?account=${encodeURIComponent(accountId)}`);
