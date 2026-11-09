/**
 * addCreatorWizard — AddCreatorModal's steps as a pure reducer. New creators start with details and platform, then
 * sign in and review the linked account. Existing drafts and relinks continue at sign-in.
 *
 *   login    the two ways in, Browser login (first, recommended) and Extension (the fallback), as the two choices at
 *            the top (`method`); a small link swaps to Fansly (`platform`, whose sign-in is the extension's session
 *            copy, so Browser login is off there). The main Add creator flow collects Creator details and platform
 *            first. The proxy is the relay's automatic one.
 *   linked   the captured account, with its account details below (nickname, tag, employees, notes): Done saves them
 *            (`submitStart` / `submitOk` / `submitErr`, `busy` while it runs) and the modal closes. A row's recovery
 *            (`recovery`) shows the account only, and Done just closes. The account's OF profile read (`profile`)
 *            prefills a blank nickname with its name, never one already there (typed, or a draft's Creator name).
 *   success  the save landed (the component closes the modal); nothing moves from here.
 *
 * Both sign-ins stay mounted while the other is shown, so a sign-in that settles late (a Browser login running while
 * the Extension tab is open) still links, to the newest account, on any step but success or a running save.
 *
 * An action the reducer refuses (a taken platform, a method Fansly has no use for, a `submitStart` while saving)
 * returns the very same state object. `useWizardReducer` relies on that: its `dispatch` runs the reducer on the
 * newest state (not the render's, so a double-click's second click sees what the first did) and answers whether
 * the action was taken — the component starts a save only when its `submitStart` was.
 */

import { useCallback, useRef, useState } from "react";

import type { AccountDetails, useSaveAccountDetails } from "@/components/setup/creatorFlow";
import type { CreatorDetails } from "@/lib/creatorProfiles";
import type { Employee } from "@/lib/relay";

export type Platform = "onlyfans" | "fansly";
/** The two ways in: a remote browser (Browserbase) or the Chrome extension's copy. */
export type Method = "browser" | "extension";

export type LinkedStep = { kind: "linked"; accountId: string; account: AccountDetails; busy: boolean };

export type WizardStep = { kind: "details" } | { kind: "platform" } | { kind: "login" } | LinkedStep | { kind: "success" };

export interface WizardState {
  step: WizardStep;
  /** A row's recovery: the platform is fixed, and the linked step has no details to save. */
  recovery: boolean;
  /** Creator details entered for a new creator, or supplied by a draft / "Link another account". */
  details: CreatorDetails;
  /** The saved Creator (a draft) the account links to. */
  draftId?: string;
  /** Platforms the Creator already has an account on: not pickable. */
  taken: readonly Platform[];
  platform: Platform;
  /** OnlyFans' way in; Fansly's is always the extension. */
  method: Method;
}

export type WizardAction =
  | { type: "detailsNext" }
  | { type: "platformNext" }
  | { type: "back" }
  | { type: "setDetails"; value: CreatorDetails }
  | { type: "setField"; field: "method"; value: Method }
  | { type: "setField"; field: "platform"; value: Platform }
  | { type: "setField"; field: "account"; value: AccountDetails }
  /** A sign-in captured the account, on its platform (a Browser login still running after a swap to Fansly links an
   *  OnlyFans account). */
  | { type: "linked"; accountId: string; account: AccountDetails; platform: Platform }
  /** The linked account's OF profile read landed: its display name (else @username) fills a blank nickname. */
  | { type: "profile"; accountId: string; name: string }
  | { type: "submitStart" }
  /** The account details saved: success. */
  | { type: "submitOk" }
  | { type: "submitErr" };

export function initialWizard({ recovery, method, draft, linkAnother }: {
  /** A row's recovery action, on this platform. */
  recovery?: Platform;
  /** The way in to open on (a row's re-link, the 2FA notification's Browser login); default Browser login. */
  method?: Method;
  draft?: CreatorDetails & { id: string };
  linkAnother?: { creator: CreatorDetails; linked: readonly Platform[] };
}): WizardState {
  const taken = linkAnother?.linked ?? [];
  const platform = recovery ?? (taken.includes("onlyfans") ? "fansly" : "onlyfans");
  return {
    step: recovery || draft || linkAnother ? { kind: "login" } : { kind: "details" },
    recovery: !!recovery,
    details: draft ?? linkAnother?.creator ?? { name: "", gender: "" },
    draftId: draft?.id,
    taken,
    platform,
    method: platform === "fansly" ? "extension" : method ?? "browser",
  };
}

/** May the step's primary button go (Done on the linked step)? The sign-in's own buttons are the cards'. */
export function canNext(s: WizardState): boolean {
  return s.step.kind === "linked" && !s.step.busy;
}

/** May the sign-in swap to `p` (the small platform link): not in a recovery, not to a taken one. */
export const canPickPlatform = (s: WizardState, p: Platform): boolean =>
  (s.step.kind === "login" || s.step.kind === "platform") && !s.recovery && !s.taken.includes(p);

const go = (state: WizardState, step: WizardStep): WizardState => ({ ...state, step });
/** A save running: its submitOk / submitErr must still land on it. */
const saving = (step: WizardStep): step is LinkedStep => step.kind === "linked" && step.busy;

function setField(state: WizardState, action: Extract<WizardAction, { type: "setField" }>): WizardState {
  const { step } = state;
  switch (action.field) {
    case "method":
      if (step.kind !== "login" || state.platform === "fansly" || state.method === action.value) return state;
      return { ...state, method: action.value };
    case "platform":
      if (state.platform === action.value || !canPickPlatform(state, action.value)) return state;
      // Fansly signs in with the extension's session copy; back on OnlyFans, Browser login comes first again.
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
      if (step.kind === "platform") return go(state, { kind: "details" });
      if (step.kind === "login" && !state.recovery && !state.draftId && !state.taken.length) return go(state, { kind: "platform" });
      return state;
    case "setField":
      return setField(state, action);
    case "linked":
      if (step.kind === "success" || saving(step)) return state;
      return { ...state, platform: action.platform, step: { kind: "linked", accountId: action.accountId, account: action.account, busy: false } };
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
  }
}

/** The name an OF profile read gives an account: its display name, else its @username (bare), else "". */
export const profileName = (me: { name?: string | null; username?: string | null } | null | undefined): string =>
  me?.name?.trim() || me?.username?.trim() || "";

/** useSaveAccountDetails' variables for the linked step's Done. A blank nickname falls back to `fallbackName` (the
 *  account's OnlyFans / Fansly name), so Done never needs a typed one. The Creator details ride along only when there
 *  are some (new creator, draft, Link another); empty details never overwrite the profile. */
export function buildAccountPayload(
  s: Pick<WizardState, "details" | "draftId">, step: LinkedStep, roster: Employee[] | null, fallbackName = "",
): Parameters<ReturnType<typeof useSaveAccountDetails>["mutate"]>[0] {
  const nickname = step.account.nickname.trim() || fallbackName.trim();
  return {
    accountId: step.accountId, before: "", roster, details: { ...step.account, nickname },
    creator: s.details.name.trim() ? s.details : undefined, draftId: s.draftId,
  };
}

/** The wizard for a component: `[state, dispatch]`, where `dispatch` runs `wizardReducer` on the newest state (a
 *  click that lands before React re-renders reads the step the previous click left) and returns true when the
 *  reducer took the action (a new state object), false when it refused it (the same one). */
export function useWizardReducer(init: Parameters<typeof initialWizard>[0]): [WizardState, (a: WizardAction) => boolean] {
  // One reduction per action: the result is stored as is (a useReducer would
  // run the reducer a second time to apply it).
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
