/**
 * addCreatorWizard — AddCreatorModal's steps as a pure reducer. The step is a discriminated union and the steps after
 * the sign-in carry the account it captured, so `linked` / `creator-details` cannot exist without one. The two steps
 * that save carry their own `busy`.
 *
 *   creators-details → select-platform → (OnlyFans) select-proxy → login → linked → creator-details → success
 *   login ⇄ role → alt ("Still unable…", OnlyFans only); login's Cancel goes back to select-proxy (OnlyFans) or
 *   select-platform.
 *
 * `next` goes only where `canNext` allows — the same check every Next button is disabled by. A save's end
 * (`submitOk`) moves on by itself; `next` on a saving step is a no-op. Creator details, platform and proxy pick live
 * beside the step, so going back keeps them, and a late edit (an avatar upload, a proxy check settling after the step
 * moved) still lands. A sign-in that settles late still links, to the newest account, on any step but success or
 * one whose save is running.
 * Saving itself is the component's (toasts, the profile and mutation hooks).
 */

import {
  creatorDetailsError, proxyChoiceReady, type AccountDetails, type ProxyChoice, type useSaveAccountDetails,
} from "@/components/setup/creatorFlow";
import type { CreatorDetails } from "@/lib/creatorProfiles";
import type { Employee } from "@/lib/relay";

export type Platform = "onlyfans" | "fansly";

export type AccountStep = { kind: "creator-details"; accountId: string; account: AccountDetails; busy: boolean };

export type WizardStep =
  | { kind: "creators-details"; busy: boolean }
  | { kind: "select-platform" }
  | { kind: "select-proxy" }
  | { kind: "login" }
  | { kind: "role" }
  | { kind: "alt" }
  | { kind: "linked"; accountId: string; account: AccountDetails }
  | AccountStep
  | { kind: "success" };

export interface WizardState {
  step: WizardStep;
  details: CreatorDetails;
  /** The saved Creator (a draft) the account links to. */
  draftId?: string;
  /** Platforms the Creator already has an account on: not pickable. */
  taken: readonly Platform[];
  platform: Platform;
  /** The Proxy selection picked; null = the default (the component's: Inflowwww proxy or No proxy, both ready). */
  picked: ProxyChoice | null;
}

export type WizardAction =
  | { type: "next" }
  | { type: "back" }
  | { type: "setField"; field: "details"; value: CreatorDetails }
  | { type: "setField"; field: "platform"; value: Platform }
  | { type: "setField"; field: "proxy"; value: ProxyChoice }
  | { type: "setField"; field: "account"; value: AccountDetails }
  /** A sign-in captured the account. */
  | { type: "linked"; accountId: string; account: AccountDetails }
  | { type: "submitStart" }
  /** The save worked: creators-details → select-platform (`draftId` when the Creator was new); creator-details →
   *  success. */
  | { type: "submitOk"; draftId?: string }
  | { type: "submitErr" };

export function initialWizard({ recovery, draft, linkAnother }: {
  /** A row's recovery action, on this platform: straight to the sign-in. */
  recovery?: Platform;
  draft?: CreatorDetails & { id: string };
  linkAnother?: { creator: CreatorDetails; linked: readonly Platform[] };
}): WizardState {
  const taken = linkAnother?.linked ?? [];
  return {
    step: recovery ? { kind: "login" } : draft || linkAnother ? { kind: "select-platform" } : { kind: "creators-details", busy: false },
    details: draft ?? linkAnother?.creator ?? { name: "", gender: "" },
    draftId: draft?.id,
    taken,
    platform: recovery ?? (taken.includes("onlyfans") ? "fansly" : "onlyfans"),
    // A recovery skips the proxy step and binds nothing.
    picked: recovery ? { type: "none" } : null,
  };
}

/** May the step move on (its Next button, or the save that does)? */
export function canNext(s: WizardState): boolean {
  const { step } = s;
  switch (step.kind) {
    case "creators-details":
      return !step.busy && !creatorDetailsError(s.details);
    case "select-platform":
      return !s.taken.includes(s.platform);
    case "select-proxy":
      return !s.picked || proxyChoiceReady(s.picked);
    case "login":
      return s.platform === "onlyfans";
    case "role":
    case "linked":
      return true;
    case "creator-details":
      return !step.busy && !!step.account.nickname.trim();
    case "alt":
    case "success":
      return false;
  }
}

const go = (state: WizardState, step: WizardStep): WizardState => ({ ...state, step });

type SaveStep = Extract<WizardStep, { busy: boolean }>;
/** A step that saves (creators-details, creator-details). */
const savesHere = (step: WizardStep): step is SaveStep => "busy" in step;
/** A step whose save is running. */
const saving = (step: WizardStep): step is SaveStep => savesHere(step) && step.busy;

function next(state: WizardState): WizardState {
  if (!canNext(state)) return state;
  const { step } = state;
  switch (step.kind) {
    case "creators-details":
      // Unsaved (a chatter, who cannot save a Creator): the flow still links the account.
      return go(state, { kind: "select-platform" });
    case "select-platform":
      return go(state, { kind: state.platform === "onlyfans" ? "select-proxy" : "login" });
    case "select-proxy":
      return go(state, { kind: "login" });
    case "login":
      return go(state, { kind: "role" });
    case "role": // Admin/employee
      return go(state, { kind: "alt" });
    case "linked":
      return go(state, { ...step, kind: "creator-details", busy: false });
    case "creator-details": // its Next is the save (submitOk)
    case "alt":
    case "success":
      return state;
  }
}

function back(state: WizardState): WizardState {
  switch (state.step.kind) {
    case "login":
      return go(state, { kind: state.platform === "onlyfans" ? "select-proxy" : "select-platform" });
    case "role": // Creator, or Cancel
    case "alt":
      return go(state, { kind: "login" });
    case "creators-details":
    case "select-platform":
    case "select-proxy":
    case "linked":
    case "creator-details":
    case "success":
      return state;
  }
}

/** Details, platform and proxy apply on any step (a late edit lands); the account only where it is edited. */
function setField(state: WizardState, action: Extract<WizardAction, { type: "setField" }>): WizardState {
  switch (action.field) {
    case "details":
      return { ...state, details: action.value };
    case "platform":
      return state.taken.includes(action.value) ? state : { ...state, platform: action.value };
    case "proxy":
      return { ...state, picked: action.value };
    case "account":
      return state.step.kind === "creator-details" ? go(state, { ...state.step, account: action.value }) : state;
  }
}

export function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  const { step } = state;
  switch (action.type) {
    case "next":
      return next(state);
    case "back":
      return back(state);
    case "setField":
      return setField(state, action);
    case "linked":
      // A save running keeps its step: its submitOk / submitErr still land.
      if (step.kind === "success" || saving(step)) return state;
      return go(state, { kind: "linked", accountId: action.accountId, account: action.account });
    case "submitStart":
      if (!savesHere(step) || !canNext(state)) return state;
      return go(state, { ...step, busy: true });
    case "submitOk":
      if (!saving(step)) return state;
      return step.kind === "creators-details"
        ? { ...state, step: { kind: "select-platform" }, draftId: action.draftId ?? state.draftId }
        : go(state, { kind: "success" });
    case "submitErr":
      return saving(step) ? go(state, { ...step, busy: false }) : state;
  }
}

/** useSaveAccountDetails' variables for creator-details' save. */
export function buildAccountPayload(
  s: Pick<WizardState, "details" | "draftId">, step: AccountStep, roster: Employee[] | null,
): Parameters<ReturnType<typeof useSaveAccountDetails>["mutate"]>[0] {
  return { accountId: step.accountId, before: "", roster, details: step.account, creator: s.details, draftId: s.draftId };
}
