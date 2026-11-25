// Back is refused while a Browser login or Extension capture runs: leaving the step unmounts the card (cancels the job) or strands `linked` on another step.
import { useCallback, useRef, useState } from "react";

import type { AccountDetails, useSaveAccountDetails } from "@/components/setup/creatorFlow";
import type { CreatorDetails } from "@/lib/creatorProfiles";
import { PLATFORMS, type Platform } from "@/lib/platform";
import type { Employee } from "@/lib/relay";

export type Method = "browser" | "extension";

export type LinkedStep = { kind: "linked"; accountId: string; account: AccountDetails; busy: boolean };

export type WizardStep = { kind: "details" } | { kind: "platform" } | { kind: "login" } | LinkedStep | { kind: "success" };

export interface WizardState {
  step: WizardStep;
  fresh: boolean;
  recovery: boolean;
  details: CreatorDetails;
  draftId?: string;
  taken: readonly Platform[];
  platform: Platform;
  method: Method;
  busy: Record<BusySource, boolean>;
}

export type BusySource = "login" | "extension" | "proxy";
const IDLE: Record<BusySource, boolean> = { login: false, extension: false, proxy: false };

export type WizardAction =
  | { type: "detailsNext" }
  | { type: "platformNext" }
  | { type: "back" }
  | { type: "setDetails"; value: CreatorDetails }
  | { type: "setField"; field: "method"; value: Method }
  | { type: "setField"; field: "platform"; value: Platform }
  | { type: "setField"; field: "account"; value: AccountDetails }
  | { type: "linked"; accountId: string; account: AccountDetails; platform: Platform }
  | { type: "profile"; accountId: string; name: string }
  | { type: "submitStart" }
  | { type: "submitOk" }
  | { type: "submitErr" }
  | { type: "busy"; source: BusySource; value: boolean };

export function initialWizard({ recovery, method, draft, linkAnother }: {
  recovery?: Platform;
  method?: Method;
  draft?: CreatorDetails & { id: string };
  linkAnother?: { creator: CreatorDetails; linked: readonly Platform[] };
}): WizardState {
  const taken = linkAnother?.linked ?? [];
  const platform = recovery ?? (PLATFORMS.find((p) => !taken.includes(p.key)) ?? PLATFORMS[0]).key;
  const fresh = !recovery && !draft && !linkAnother;
  return {
    step: fresh ? { kind: "details" } : { kind: "login" },
    fresh,
    recovery: !!recovery,
    details: draft ?? linkAnother?.creator ?? { name: "", gender: "" },
    draftId: draft?.id,
    taken,
    platform,
    method: platform === "fansly" ? "extension" : method ?? "browser",
    busy: IDLE,
  };
}

export function canNext(s: WizardState): boolean {
  return s.step.kind === "linked" && !s.step.busy && !s.busy.proxy;
}

export const canBack = (s: WizardState): boolean =>
  s.step.kind === "platform" || (s.step.kind === "login" && s.fresh && !s.busy.login && !s.busy.extension);

// Not closable while Extension capture/attach or proxy Connect runs: those relay calls would go on unseen.
export const canClose = (s: WizardState): boolean => !s.busy.extension && !s.busy.proxy;

export const canPickPlatform = (s: WizardState, p: Platform): boolean =>
  (s.step.kind === "login" || s.step.kind === "platform") && !s.recovery && !s.taken.includes(p);

const go = (state: WizardState, step: WizardStep): WizardState => ({ ...state, step });
const saving = (step: WizardStep): step is LinkedStep => step.kind === "linked" && step.busy;

function setField(state: WizardState, action: Extract<WizardAction, { type: "setField" }>): WizardState {
  const { step } = state;
  switch (action.field) {
    case "method":
      if (step.kind !== "login" || state.platform === "fansly" || state.method === action.value) return state;
      return { ...state, method: action.value };
    case "platform":
      if (state.platform === action.value || !canPickPlatform(state, action.value)) return state;
      return { ...state, platform: action.value, method: action.value === "fansly" ? "extension" : "browser" };
    case "account":
      return step.kind === "linked" && !step.busy ? go(state, { ...step, account: action.value }) : state;
  }
}

export function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  const { step } = state;
  switch (action.type) {
    case "setDetails":
      return step.kind === "details" ? { ...state, details: action.value } : state;
    case "detailsNext":
      return step.kind === "details" ? go(state, { kind: "platform" }) : state;
    case "platformNext":
      return step.kind === "platform" ? go(state, { kind: "login" }) : state;
    case "back":
      if (!canBack(state)) return state;
      return go(state, step.kind === "platform" ? { kind: "details" } : { kind: "platform" });
    case "setField":
      return setField(state, action);
    case "linked":
      if (step.kind !== "login") return state;
      return {
        ...state, platform: action.platform, busy: { ...state.busy, login: false, extension: false },
        step: { kind: "linked", accountId: action.accountId, account: action.account, busy: false },
      };
    case "profile":
      if (step.kind !== "linked" || step.busy || state.recovery || step.accountId !== action.accountId
          || !action.name.trim() || step.account.nickname.trim()) return state;
      return go(state, { ...step, account: { ...step.account, nickname: action.name.trim() } });
    case "submitStart":
      if (step.kind !== "linked" || state.recovery || !canNext(state)) return state;
      return go(state, { ...step, busy: true });
    case "submitOk":
      return saving(step) ? go(state, { kind: "success" }) : state;
    case "submitErr":
      return saving(step) ? go(state, { ...step, busy: false }) : state;
    case "busy":
      return state.busy[action.source] === action.value ? state
        : { ...state, busy: { ...state.busy, [action.source]: action.value } };
  }
}

export const profileName = (me: { name?: string | null; username?: string | null } | null | undefined): string =>
  me?.name?.trim() || me?.username?.trim() || "";

export function buildAccountPayload(
  s: Pick<WizardState, "details" | "draftId">, step: LinkedStep, roster: Employee[] | null, fallbackName = "",
): Parameters<ReturnType<typeof useSaveAccountDetails>["mutate"]>[0] {
  const nickname = step.account.nickname.trim() || fallbackName.trim();
  return {
    accountId: step.accountId, before: "", roster, details: { ...step.account, nickname },
    creator: s.details.name.trim() ? s.details : undefined, draftId: s.draftId,
  };
}

export function useWizardReducer(init: Parameters<typeof initialWizard>[0]): [WizardState, (a: WizardAction) => boolean] {
  // One reduction per action: a useReducer would run the reducer a second time.
  const [state, setState] = useState(() => initialWizard(init));
  const latest = useRef(state);
  const dispatch = useCallback((action: WizardAction): boolean => {
    const after = wizardReducer(latest.current, action);
    if (after === latest.current) return false;
    latest.current = after;
    setState(after);
    return true;
  }, []);
  return [state, dispatch];
}
