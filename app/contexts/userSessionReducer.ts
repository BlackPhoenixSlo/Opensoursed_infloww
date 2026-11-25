import type { AuthedUserDTO } from "./UserContext";

export type ProbePhase = "boot" | "revalidate";

export type BootStatus = "probing" | "settled" | "unreachable";

export type AuthBanner = "blocked" | "slow";

export interface UserSessionState {
  user: AuthedUserDTO | null;
  boot: BootStatus;
  painted: AuthedUserDTO | null;
  revalidating: boolean;
  banner: AuthBanner | null;
  formUp: boolean;
}

export type UserSessionAction =
  | { type: "bootStart"; snapshot: AuthedUserDTO | null }
  | { type: "bootOk"; user: AuthedUserDTO | null }
  | { type: "bootNetErr" }
  | { type: "bootAuthErr" }
  | { type: "bootBlocked" }
  | { type: "probeSlow" }
  | { type: "revalidateStart"; hidden: boolean }
  | { type: "revalidateOk"; user: AuthedUserDTO | null }
  | { type: "revalidateNetErr" }
  | { type: "revalidateAuthErr" }
  | { type: "confirmed"; user: AuthedUserDTO }
  | { type: "unconfirmed"; user: AuthedUserDTO }
  | { type: "logout" };

export type UserSessionEffect =
  | { type: "fetchMe"; phase: ProbePhase }
  | { type: "snapshot"; user: AuthedUserDTO | null }
  | { type: "wipeCaches" }
  | { type: "dropProbes" };

export interface UserSessionStep {
  state: UserSessionState;
  effects: UserSessionEffect[];
}

export const initialUserSession: UserSessionState = {
  user: null, boot: "probing", painted: null, revalidating: false, banner: null, formUp: false,
};

export type MeOutcome =
  | { type: "answered"; user: AuthedUserDTO | null }
  | { type: "refused"; status: number }
  | { type: "netError"; error: unknown };

const PROBE_ACTIONS = {
  boot: { ok: "bootOk", auth: "bootAuthErr", net: "bootNetErr", blocked: "bootBlocked" },
  revalidate: { ok: "revalidateOk", auth: "revalidateAuthErr", net: "revalidateNetErr", blocked: "revalidateNetErr" },
} as const;

export function probeAction(phase: ProbePhase, o: MeOutcome): UserSessionAction {
  const t = PROBE_ACTIONS[phase];
  if (o.type === "answered") return { type: t.ok, user: o.user };
  if (o.type === "refused" && o.status === 403) return { type: t.blocked };
  return { type: o.type === "refused" && o.status === 401 ? t.auth : t.net };
}

export type GateScreen = "loading" | "signed-in" | "retry" | "login";

export function gateScreen(
  s: Pick<UserSessionState, "user" | "boot" | "formUp">,
  chatter: { present: boolean; loading: boolean },
): GateScreen {
  if (s.formUp) return s.user || chatter.present ? "signed-in" : "login";
  if ((s.boot === "probing" && !s.user) || chatter.loading) return "loading";
  if (s.user || chatter.present) return "signed-in";
  return s.boot === "unreachable" ? "retry" : "login";
}

function commit(state: UserSessionState, user: AuthedUserDTO | null): UserSessionStep {
  return { state: { ...state, user }, effects: [{ type: "snapshot", user }] };
}

function settleBoot(state: UserSessionState, user: AuthedUserDTO | null): UserSessionStep {
  // Only boot wipes caches on an identity change; revalidation never does.
  const switched = !!state.painted && !!user && user.user_id !== state.painted.user_id;
  const step = commit({ ...state, boot: "settled", painted: null, banner: null }, user);
  return switched ? { ...step, effects: [{ type: "wipeCaches" }, ...step.effects] } : step;
}

function adopt(state: UserSessionState, user: AuthedUserDTO | null, snapshot: AuthedUserDTO | null): UserSessionStep {
  return {
    state: { user, boot: "settled", painted: null, revalidating: false, banner: null, formUp: !!user && state.formUp },
    effects: [{ type: "dropProbes" }, { type: "snapshot", user: snapshot }],
  };
}

export function decideUserSession(state: UserSessionState, action: UserSessionAction): UserSessionStep {
  switch (action.type) {
    case "bootStart": {
      if (state.boot === "settled" || (state.boot === "probing" && state.banner)) return { state, effects: [] };
      const s: UserSessionState = action.snapshot
        ? { ...state, user: action.snapshot, boot: "probing", painted: action.snapshot, revalidating: false,
          banner: null, formUp: false }
        : { ...state, boot: "probing", revalidating: false };
      return { state: s, effects: [{ type: "dropProbes" }, { type: "fetchMe", phase: "boot" }] };
    }
    case "bootOk":
      return settleBoot(state, action.user);
    case "bootAuthErr":
      return settleBoot(state, null);
    // Unreachable relay neither signs in nor out: a network hiccup must not outlive-cookie a snapshotted session, so nobody is shown signed in.
    case "bootNetErr": {
      const slow = state.banner === "slow";
      return { state: { ...state, user: null, boot: "unreachable", banner: slow ? "slow" : null, formUp: slow }, effects: [] };
    }
    case "bootBlocked":
      return { state: { ...state, user: null, boot: "unreachable", banner: "blocked", formUp: true }, effects: [] };
    case "probeSlow":
      if (state.boot !== "probing" || state.user) return { state, effects: [] };
      return { state: { ...state, banner: "slow", formUp: true }, effects: [] };
    // No-op while unreachable: only Retry re-runs the boot, so a focus can't shut the gate on a signed-in shell.
    case "revalidateStart":
      if (action.hidden || state.revalidating || state.boot !== "settled") return { state, effects: [] };
      return { state: { ...state, revalidating: true }, effects: [{ type: "fetchMe", phase: "revalidate" }] };
    case "revalidateOk":
      return commit({ ...state, revalidating: false }, action.user);
    case "revalidateAuthErr":
      return commit({ ...state, revalidating: false }, null);
    // Transient hiccup: keep the user, retry on next focus.
    case "revalidateNetErr":
      return { state: { ...state, revalidating: false }, effects: [] };
    case "confirmed":
      return adopt(state, action.user, action.user);
    case "unconfirmed":
      return adopt(state, action.user, null);
    case "logout":
      return adopt(state, null, null);
  }
}
