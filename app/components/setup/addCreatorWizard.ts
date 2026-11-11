/**
 * addCreatorWizard — AddCreatorModal's steps as a pure reducer. New creators start with details and platform, then
 * sign in and review the linked account. Existing drafts and relinks continue at sign-in.
 *
 *   login    the two ways in, Browser login (first, recommended) and Extension (the fallback), as the two choices at
 *            the top (`method`); a small link swaps to Fansly (`platform`, whose sign-in is the extension's session
 *            copy, so Browser login is off there). The main Add creator flow collects Creator details and platform
 *            first. The proxy is the relay's automatic one.
 *   linked   the captured account, with its account details below (nickname, tag, employees, notes): Done saves them
 *            (`submitStart` / `submitOk` / `submitErr`, `busy` while it runs) and the modal closes; not while the
 *            optional proxy editor is working (`busy.proxy`). A row's recovery (`recovery`) shows the account only, and
 *            Done just closes. The nickname starts as the Creator name; the account's OF profile read (`profile`)
 *            fills it only when it is blank (an unnamed draft, or Link another of an account with no name), never
 *            one already there.
 *   success  the save landed (the component closes the modal); nothing moves from here.
 *
 * Both sign-ins stay mounted on the sign-in step while the other is shown, so a Browser login still running while the
 * Extension panel is open still links. Only the sign-in step takes a `linked`: once an account is linked, a late one
 * (another sign-in settling) is refused, so it can't replace the linked account or its typed details. While a Browser
 * login runs (`busy.login`) Back is refused: leaving the sign-in step unmounts the card, which cancels the job. So
 * is it while the Extension's capture or attach runs, or waits on Retry / Continue (`busy.extension`): its `linked`
 * would land on another step and be refused, the account linked with its details never saved. Each child reports
 * into `busy` with one action (`busy`, its source) through `useReportBusy`.
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
  /** The header's Add creator: a brand-new Creator (details and platform first). Not a draft, Link another or recovery. */
  fresh: boolean;
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
  /** What the children report as under way: `login` a Browser login job (Back refused), `extension` the Extension's
   *  capture / attach or its wait on Retry / Continue (Back refused), `proxy` the linked step's proxy editor (Done
   *  waits). */
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
  /** A sign-in captured the account, on its platform (a Browser login still running after a swap to Fansly links an
   *  OnlyFans account). Taken on the sign-in step only. */
  | { type: "linked"; accountId: string; account: AccountDetails; platform: Platform }
  /** The linked account's OF profile read landed: its display name (else @username) fills a blank nickname. */
  | { type: "profile"; accountId: string; name: string }
  | { type: "submitStart" }
  /** The account details saved: success. */
  | { type: "submitOk" }
  | { type: "submitErr" }
  /** A child's busy report (useReportBusy). */
  | { type: "busy"; source: BusySource; value: boolean };

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

/** May the step's primary button go (Done on the linked step)? The sign-in's own buttons are the cards'. */
export function canNext(s: WizardState): boolean {
  return s.step.kind === "linked" && !s.step.busy && !s.busy.proxy;
}

/** Is there a Back (platform → details; a new Creator's sign-in → platform, not while a sign-in is under way)? */
export const canBack = (s: WizardState): boolean =>
  s.step.kind === "platform" || (s.step.kind === "login" && s.fresh && !s.busy.login && !s.busy.extension);

/** May the modal close (×, Escape, Cancel)? Not while the Extension's capture / attach or the linked step's proxy
 *  Connect is under way: those relay calls would go on unseen (a silent proxy move, a link and blob write after close).
 *  A Browser login may: unmounting its card stops the job. */
export const canClose = (s: WizardState): boolean => !s.busy.extension && !s.busy.proxy;

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
