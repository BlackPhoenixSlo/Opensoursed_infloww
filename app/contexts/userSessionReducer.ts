/**
 * The signed-in user's session as a pure transition: `decideUserSession(state,
 * action) -> { state, effects }`. UserContext is the shell — it turns fetch
 * results (via `probeAction`), focus/visibility and the login/logout calls
 * into actions, and performs the effects in order. The rules:
 *
 *   • `boot` is where the boot probe is: `probing` (in flight — the gate
 *     stays shut unless a warm-boot snapshot is painted), `settled`, or
 *     `unreachable`.
 *   • `bootStart` (mount; the retry screen's Retry with no snapshot) paints
 *     the snapshot, if there is one, and probes /auth/me (`fetchMe` "boot"),
 *     dropping any boot probe already in flight (an effect re-run). Once the
 *     boot settled it is a no-op: a session is never rebooted in place.
 *   • `bootOk` adopts what the boot probe answers (null = signed out);
 *     `bootAuthErr` (401) signs out. If it answers a DIFFERENT user than the
 *     snapshot painted, the caches already read under that identity are wiped
 *     first (`wipeCaches`), as a login would.
 *   • `bootNetErr` (relay unreachable) neither signs in nor out: `user` null,
 *     `boot` unreachable — the gate shows a retry screen, not the login form.
 *     The snapshot is kept (the next boot still paints warm) and so is
 *     `painted` (the retry's answer still wipes on a switch). The snapshot
 *     must not turn a network hiccup into a session that outlives its cookie,
 *     so nobody is shown signed in until the server says so.
 *   • `revalidateStart` (window focus, tab visible again) probes again —
 *     only once the boot settled, and unless the tab is hidden or a
 *     revalidation is already in flight. While `unreachable` it is a no-op:
 *     only Retry re-runs the boot (a focus must not shut the gate on a
 *     signed-in chatter's shell), so only boot answers ever settle a boot.
 *   • `revalidateOk` adopts the answer (null signs out), `revalidateAuthErr`
 *     signs out, `revalidateNetErr` KEEPS the current user (retry on the next
 *     focus). It never wipes on an identity change — only boot does.
 *   • `probeAction` sorts a probe's outcome: a 2xx is Ok (a signed-out cookie
 *     is a 200 `null`), 401 is AuthErr, a thrown fetch or any other status
 *     (a 5xx from the proxy in front of a dead relay, a 429, a 403) is NetErr.
 *   • `confirmed` is a user the server just returned outside the probes
 *     (login, register, impersonation's /auth/me); `unconfirmed` is
 *     impersonation's synthesized stub, which must never be snapshotted;
 *     `logout` (logout, the chatter flip, stopImpersonating answered no one)
 *     signs out. Each supersedes any probe in flight (`dropProbes`: its late
 *     answer would speak for the cookie before the flow) and settles the boot.
 *     The flows' own cache wipes and logout's navigation stay in those flows:
 *     they are unconditional.
 *
 * Every confirmed user change goes with a `snapshot` effect (write it; null
 * or an impersonation overlay clears it — lib/authSnapshot.ts), so the two
 * can't drift; the unconfirmed ones (bootStart's paint, bootNetErr's blank)
 * leave the snapshot as it is. Redirecting a signed-out user is the gate's job (`gateScreen`), so
 * there is no redirect effect.
 */

import type { AuthedUserDTO } from "./UserContext";

export type ProbePhase = "boot" | "revalidate";

export type BootStatus = "probing" | "settled" | "unreachable";

export interface UserSessionState {
  user: AuthedUserDTO | null;
  boot: BootStatus;
  /** The snapshot boot painted, until a boot answer settles it. */
  painted: AuthedUserDTO | null;
  /** A focus/visibility revalidation is in flight. */
  revalidating: boolean;
}

export type UserSessionAction =
  | { type: "bootStart"; snapshot: AuthedUserDTO | null }
  /** Boot /auth/me answered 2xx; `user` is null when the body carries no user_id. */
  | { type: "bootOk"; user: AuthedUserDTO | null }
  /** Boot /auth/me threw, timed out, or answered a non-401 error status. */
  | { type: "bootNetErr" }
  /** Boot /auth/me answered 401. */
  | { type: "bootAuthErr" }
  | { type: "revalidateStart"; hidden: boolean }
  | { type: "revalidateOk"; user: AuthedUserDTO | null }
  | { type: "revalidateNetErr" }
  | { type: "revalidateAuthErr" }
  | { type: "confirmed"; user: AuthedUserDTO }
  | { type: "unconfirmed"; user: AuthedUserDTO }
  | { type: "logout" };

export type UserSessionEffect =
  | { type: "fetchMe"; phase: ProbePhase }
  /** writeAuthSnapshot(user): null clears it. */
  | { type: "snapshot"; user: AuthedUserDTO | null }
  | { type: "wipeCaches" }
  /** Drop the answer of every /auth/me probe in flight. */
  | { type: "dropProbes" };

export interface UserSessionStep {
  state: UserSessionState;
  effects: UserSessionEffect[];
}

export const initialUserSession: UserSessionState = {
  user: null, boot: "probing", painted: null, revalidating: false,
};

/** What one GET /auth/me ended in. */
export type MeOutcome =
  | { type: "answered"; user: AuthedUserDTO | null }
  | { type: "refused"; status: number }
  /** The fetch threw or the body was unreadable; `error` is what was thrown. */
  | { type: "netError"; error: unknown };

const PROBE_ACTIONS = {
  boot: { ok: "bootOk", auth: "bootAuthErr", net: "bootNetErr" },
  revalidate: { ok: "revalidateOk", auth: "revalidateAuthErr", net: "revalidateNetErr" },
} as const;

/** A /auth/me outcome as the action for its phase. */
export function probeAction(phase: ProbePhase, o: MeOutcome): UserSessionAction {
  const t = PROBE_ACTIONS[phase];
  if (o.type === "answered") return { type: t.ok, user: o.user };
  return { type: o.type === "refused" && o.status === 401 ? t.auth : t.net };
}

export type GateScreen = "loading" | "signed-in" | "retry" | "login";

/** Where AuthGate sends a session; a signed-in chatter is signed in too, and
 *  the gate waits on the chatter probe as well. */
export function gateScreen(
  s: Pick<UserSessionState, "user" | "boot">,
  chatter: { present: boolean; loading: boolean },
): GateScreen {
  if ((s.boot === "probing" && !s.user) || chatter.loading) return "loading";
  if (s.user || chatter.present) return "signed-in";
  return s.boot === "unreachable" ? "retry" : "login";
}

/** Commit a server-confirmed principal (and its snapshot). */
function commit(state: UserSessionState, user: AuthedUserDTO | null): UserSessionStep {
  return { state: { ...state, user }, effects: [{ type: "snapshot", user }] };
}

/** The boot probe settled with `user` (null = signed out). */
function settleBoot(state: UserSessionState, user: AuthedUserDTO | null): UserSessionStep {
  const switched = !!state.painted && !!user && user.user_id !== state.painted.user_id;
  const step = commit({ ...state, boot: "settled", painted: null }, user);
  return switched ? { ...step, effects: [{ type: "wipeCaches" }, ...step.effects] } : step;
}

/** A flow's principal: drops the probes in flight and settles the boot. */
function adopt(user: AuthedUserDTO | null, snapshot: AuthedUserDTO | null): UserSessionStep {
  return {
    state: { user, boot: "settled", painted: null, revalidating: false },
    effects: [{ type: "dropProbes" }, { type: "snapshot", user: snapshot }],
  };
}

export function decideUserSession(state: UserSessionState, action: UserSessionAction): UserSessionStep {
  switch (action.type) {
    case "bootStart": {
      if (state.boot === "settled") return { state, effects: [] };
      const s: UserSessionState = action.snapshot
        ? { ...state, user: action.snapshot, boot: "probing", painted: action.snapshot, revalidating: false }
        : { ...state, boot: "probing", revalidating: false };
      return { state: s, effects: [{ type: "dropProbes" }, { type: "fetchMe", phase: "boot" }] };
    }
    case "bootOk":
      return settleBoot(state, action.user);
    case "bootAuthErr":
      return settleBoot(state, null);
    case "bootNetErr":
      return { state: { ...state, user: null, boot: "unreachable" }, effects: [] };
    case "revalidateStart":
      if (action.hidden || state.revalidating || state.boot !== "settled") return { state, effects: [] };
      return { state: { ...state, revalidating: true }, effects: [{ type: "fetchMe", phase: "revalidate" }] };
    case "revalidateOk":
      return commit({ ...state, revalidating: false }, action.user);
    case "revalidateAuthErr":
      return commit({ ...state, revalidating: false }, null);
    case "revalidateNetErr":
      // A transient hiccup — keep the user, retry next focus.
      return { state: { ...state, revalidating: false }, effects: [] };
    case "confirmed":
      return adopt(action.user, action.user);
    case "unconfirmed":
      return adopt(action.user, null);
    case "logout":
      return adopt(null, null);
  }
}
