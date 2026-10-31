import { describe, expect, it } from "vitest";

import type { AuthedUserDTO } from "./UserContext";
import {
  decideUserSession, gateScreen, initialUserSession, probeAction,
  type GateScreen, type MeOutcome, type ProbePhase, type UserSessionAction, type UserSessionEffect,
  type UserSessionState,
} from "./userSessionReducer";

const ALICE: AuthedUserDTO = { user_id: "u1", username: "alice" };
const BOB: AuthedUserDTO = { user_id: "u2", username: "bob" };

/** Run actions from `from`, collecting every effect in order. */
function run(actions: UserSessionAction[], from: UserSessionState = initialUserSession) {
  const effects: UserSessionEffect[] = [];
  const state = actions.reduce((s, a) => {
    const step = decideUserSession(s, a);
    effects.push(...step.effects);
    return step.state;
  }, from);
  return { state, effects };
}

const bootedWith = (snapshot: AuthedUserDTO | null) => run([{ type: "bootStart", snapshot }]).state;
/** Signed in as ALICE, boot settled, nothing in flight. */
const signedIn = run([{ type: "bootStart", snapshot: null }, { type: "bootOk", user: ALICE }]).state;
const revalidating = run([{ type: "revalidateStart", hidden: false }], signedIn).state;
/** The boot probe over an ALICE snapshot could not reach the relay. */
const unreachable = run([{ type: "bootStart", snapshot: ALICE }, { type: "bootNetErr" }]).state;
const settled: UserSessionState = { ...initialUserSession, boot: "settled" };
/** No chatter signed in, none being probed. */
const NO_CHATTER = { present: false, loading: false };
const CHATTER = { present: true, loading: false };

describe("the three rules", () => {
  it.each<[string, UserSessionState, UserSessionAction, GateScreen]>([
    ["net error during revalidate keeps the user signed in", revalidating, { type: "revalidateNetErr" }, "signed-in"],
    ["net error during boot (snapshot painted) shows the retry state", bootedWith(ALICE), { type: "bootNetErr" }, "retry"],
    ["net error during boot (no snapshot) shows the retry state", bootedWith(null), { type: "bootNetErr" }, "retry"],
    ["401 during boot signs out", bootedWith(ALICE), { type: "bootAuthErr" }, "login"],
    ["401 during revalidate signs out", revalidating, { type: "revalidateAuthErr" }, "login"],
  ])("%s", (_name, from, action, want) => {
    expect(gateScreen(decideUserSession(from, action).state, NO_CHATTER)).toBe(want);
  });
});

describe("gateScreen", () => {
  it.each<[string, UserSessionState, { present: boolean; loading: boolean }, GateScreen]>([
    ["boot probing, nothing painted: wait", bootedWith(null), NO_CHATTER, "loading"],
    ["boot probing over a snapshot: signed in", bootedWith(ALICE), NO_CHATTER, "signed-in"],
    ["settled, nobody: the sign-in form", settled, NO_CHATTER, "login"],
    ["unreachable: the retry screen", unreachable, NO_CHATTER, "retry"],
    ["the chatter probe still running: wait", settled, { present: false, loading: true }, "loading"],
    ["unreachable but a chatter is signed in: signed in", unreachable, CHATTER, "signed-in"],
    ["settled, a chatter: signed in", settled, CHATTER, "signed-in"],
  ])("%s", (_name, s, chatter, want) => {
    expect(gateScreen(s, chatter)).toBe(want);
  });
});

describe("probeAction sorts /auth/me outcomes", () => {
  const thrown = new TypeError("Failed to fetch");
  it.each<[ProbePhase, MeOutcome, UserSessionAction]>([
    ["boot", { type: "answered", user: ALICE }, { type: "bootOk", user: ALICE }],
    ["boot", { type: "answered", user: null }, { type: "bootOk", user: null }],
    ["boot", { type: "refused", status: 401 }, { type: "bootAuthErr" }],
    ["boot", { type: "refused", status: 403 }, { type: "bootNetErr" }],
    ["boot", { type: "refused", status: 500 }, { type: "bootNetErr" }],
    ["boot", { type: "refused", status: 502 }, { type: "bootNetErr" }],
    ["boot", { type: "refused", status: 429 }, { type: "bootNetErr" }],
    ["boot", { type: "netError", error: thrown }, { type: "bootNetErr" }],
    ["revalidate", { type: "answered", user: BOB }, { type: "revalidateOk", user: BOB }],
    ["revalidate", { type: "refused", status: 401 }, { type: "revalidateAuthErr" }],
    ["revalidate", { type: "refused", status: 403 }, { type: "revalidateNetErr" }],
    ["revalidate", { type: "refused", status: 503 }, { type: "revalidateNetErr" }],
    ["revalidate", { type: "netError", error: thrown }, { type: "revalidateNetErr" }],
  ])("%s %j -> %j", (phase, outcome, want) => {
    expect(probeAction(phase, outcome)).toEqual(want);
  });
});

const BOOT_PROBE: UserSessionEffect[] = [{ type: "dropProbes" }, { type: "fetchMe", phase: "boot" }];

describe("bootStart", () => {
  it.each<[string, AuthedUserDTO | null, Partial<UserSessionState>]>([
    ["no snapshot: the gate stays shut, nobody painted", null, { user: null, boot: "probing", painted: null }],
    ["a snapshot paints it and opens the gate", ALICE, { user: ALICE, boot: "probing", painted: ALICE }],
  ])("%s, and probes /auth/me", (_name, snapshot, want) => {
    const { state, effects } = run([{ type: "bootStart", snapshot }]);
    expect(state).toMatchObject(want);
    expect(effects).toEqual(BOOT_PROBE);
  });

  it("an effect re-run while the boot probe is in flight drops it and probes again", () => {
    const step = decideUserSession(bootedWith(ALICE), { type: "bootStart", snapshot: ALICE });
    expect(step.state).toEqual(bootedWith(ALICE));
    expect(step.effects).toEqual(BOOT_PROBE);
  });

  it.each<[string, UserSessionState]>([
    ["signed in", signedIn],
    ["mid-revalidation: its answer still lands and clears the in-flight flag", revalidating],
    ["signed out", settled],
  ])("once the boot settled, a no-op (%s)", (_name, from) => {
    for (const snapshot of [null, ALICE]) {
      const step = decideUserSession(from, { type: "bootStart", snapshot });
      expect(step.state).toBe(from);
      expect(step.effects).toEqual([]);
    }
  });
});

describe("the boot probe settles the boot and decides", () => {
  it.each<[string, AuthedUserDTO | null, UserSessionAction, AuthedUserDTO | null, UserSessionEffect[]]>([
    ["bootOk, no snapshot", null, { type: "bootOk", user: ALICE }, ALICE, [{ type: "snapshot", user: ALICE }]],
    ["bootOk, same user as the snapshot: no wipe", ALICE, { type: "bootOk", user: ALICE }, ALICE,
      [{ type: "snapshot", user: ALICE }]],
    ["bootOk, another user than the snapshot: wipe first", ALICE, { type: "bootOk", user: BOB }, BOB,
      [{ type: "wipeCaches" }, { type: "snapshot", user: BOB }]],
    ["bootOk null (signed-out cookie) over a snapshot: signed out, no wipe", ALICE, { type: "bootOk", user: null },
      null, [{ type: "snapshot", user: null }]],
    ["bootAuthErr over a snapshot: signed out", ALICE, { type: "bootAuthErr" }, null,
      [{ type: "snapshot", user: null }]],
    ["bootAuthErr, no snapshot: signed out", null, { type: "bootAuthErr" }, null,
      [{ type: "snapshot", user: null }]],
  ])("%s", (_name, snapshot, action, user, effects) => {
    const step = decideUserSession(bootedWith(snapshot), action);
    expect(step.state).toEqual({ ...settled, user });
    expect(step.effects).toEqual(effects);
  });

  it.each<[string, AuthedUserDTO | null]>([
    ["over a snapshot", ALICE],
    ["with no snapshot", null],
  ])("bootNetErr %s: nobody shown, unreachable, snapshot and painted kept, no effects", (_name, snapshot) => {
    const step = decideUserSession(bootedWith(snapshot), { type: "bootNetErr" });
    expect(step.state).toEqual({ ...initialUserSession, boot: "unreachable", painted: snapshot });
    expect(step.effects).toEqual([]);
  });
});

describe("revalidateStart (focus / visible)", () => {
  it.each<[string, UserSessionState, boolean, boolean]>([
    ["signed in, visible: probes", signedIn, false, true],
    ["signed out, visible: probes", settled, false, true],
    ["hidden tab: no-op", signedIn, true, false],
    ["a revalidation already in flight: no double fetch", revalidating, false, false],
    ["the boot probe in flight over a snapshot: no-op, its answer decides", bootedWith(ALICE), false, false],
    ["the boot probe in flight, nothing painted: no-op", bootedWith(null), false, false],
    ["the retry state: no-op, only Retry re-runs the boot", unreachable, false, false],
    ["the retry state, hidden: no-op", unreachable, true, false],
  ])("%s", (_name, from, hidden, fetches) => {
    const step = decideUserSession(from, { type: "revalidateStart", hidden });
    if (fetches) {
      expect(step.effects).toEqual([{ type: "fetchMe", phase: "revalidate" }]);
      expect(step.state).toEqual({ ...from, revalidating: true });
    } else {
      expect(step.effects).toEqual([]);
      expect(step.state).toBe(from);
    }
  });

  it("two focus events back to back fetch once", () => {
    const { effects } = run(
      [{ type: "revalidateStart", hidden: false }, { type: "revalidateStart", hidden: false }], signedIn,
    );
    expect(effects).toEqual([{ type: "fetchMe", phase: "revalidate" }]);
  });

  it("only the boot probe answers a boot: a focus during it adds no revalidate answer", () => {
    const { state, effects } = run([
      { type: "bootStart", snapshot: ALICE },
      { type: "revalidateStart", hidden: false },
      { type: "bootNetErr" },
    ]);
    expect(effects).toEqual(BOOT_PROBE);
    expect(gateScreen(state, NO_CHATTER)).toBe("retry");
  });

  it("a focus while unreachable keeps a signed-in chatter's shell up", () => {
    const { state, effects } = run([{ type: "revalidateStart", hidden: false }], unreachable);
    expect(effects).toEqual([]);
    expect(gateScreen(state, CHATTER)).toBe("signed-in");
  });
});

describe("from the retry state, Retry (bootStart, no snapshot) is the boot again", () => {
  const RETRY: UserSessionAction = { type: "bootStart", snapshot: null };

  it("waits on the gate, keeps what was painted, probes as boot", () => {
    const step = decideUserSession(unreachable, RETRY);
    expect(step.state).toEqual({ ...unreachable, boot: "probing" });
    expect(step.effects).toEqual(BOOT_PROBE);
    expect(gateScreen(step.state, NO_CHATTER)).toBe("loading");
  });

  it("an answer of another user than the first paint still wipes", () => {
    const { state, effects } = run([RETRY, { type: "bootOk", user: BOB }], unreachable);
    expect(state).toEqual({ ...settled, user: BOB });
    expect(effects.slice(-2)).toEqual([{ type: "wipeCaches" }, { type: "snapshot", user: BOB }]);
  });

  it("an answer of the painted user: signed in, no wipe", () => {
    const { state, effects } = run([RETRY, { type: "bootOk", user: ALICE }], unreachable);
    expect(state).toEqual({ ...settled, user: ALICE });
    expect(effects.slice(BOOT_PROBE.length)).toEqual([{ type: "snapshot", user: ALICE }]);
  });

  it("failing again goes back to the retry state", () => {
    const { state } = run([RETRY, { type: "bootNetErr" }], unreachable);
    expect(state).toEqual(unreachable);
  });
});

describe("the revalidate probe: a network error keeps the user, an auth error signs out", () => {
  it.each<[string, UserSessionAction, AuthedUserDTO | null, UserSessionEffect[]]>([
    ["revalidateNetErr: user kept, snapshot untouched", { type: "revalidateNetErr" }, ALICE, []],
    ["revalidateAuthErr: signed out", { type: "revalidateAuthErr" }, null, [{ type: "snapshot", user: null }]],
    ["revalidateOk null: signed out", { type: "revalidateOk", user: null }, null, [{ type: "snapshot", user: null }]],
    ["revalidateOk same user: adopted", { type: "revalidateOk", user: ALICE }, ALICE,
      [{ type: "snapshot", user: ALICE }]],
    ["revalidateOk another user: adopted WITHOUT a wipe (only boot wipes)", { type: "revalidateOk", user: BOB }, BOB,
      [{ type: "snapshot", user: BOB }]],
  ])("%s", (_name, action, user, effects) => {
    const step = decideUserSession(revalidating, action);
    expect(step.state).toEqual({ ...signedIn, user, revalidating: false });
    expect(step.effects).toEqual(effects);
  });

  it("after any outcome the next focus probes again", () => {
    for (const outcome of [
      { type: "revalidateNetErr" },
      { type: "revalidateAuthErr" },
      { type: "revalidateOk", user: ALICE },
    ] satisfies UserSessionAction[]) {
      const { effects } = run([outcome, { type: "revalidateStart", hidden: false }], revalidating);
      expect(effects.at(-1)).toEqual({ type: "fetchMe", phase: "revalidate" });
    }
  });
});

describe("principals from the flows (login, logout, impersonation) supersede the probes", () => {
  it.each<[string, UserSessionAction, AuthedUserDTO | null, AuthedUserDTO | null]>([
    ["confirmed user: committed and snapshotted", { type: "confirmed", user: BOB }, BOB, BOB],
    ["logout (logout, chatter flip, stopImpersonating to no one): signed out, snapshot cleared", { type: "logout" },
      null, null],
    ["unconfirmed impersonation stub: shown, never snapshotted", { type: "unconfirmed", user: BOB }, BOB, null],
  ])("%s", (_name, action, user, snapshot) => {
    for (const from of [signedIn, revalidating, bootedWith(ALICE), bootedWith(null), unreachable]) {
      const step = decideUserSession(from, action);
      expect(step.state).toEqual({ ...settled, user });
      expect(step.effects).toEqual([{ type: "dropProbes" }, { type: "snapshot", user: snapshot }]);
    }
  });

  it.each<[string, UserSessionAction, GateScreen]>([
    ["logout from the retry state: the sign-in form", { type: "logout" }, "login"],
    ["confirmed from the retry state: signed in", { type: "confirmed", user: ALICE }, "signed-in"],
  ])("%s", (_name, action, want) => {
    expect(gateScreen(decideUserSession(unreachable, action).state, NO_CHATTER)).toBe(want);
  });

  it("after a logout mid-revalidate, the next focus probes again", () => {
    const { effects } = run([{ type: "logout" }, { type: "revalidateStart", hidden: false }], revalidating);
    expect(effects.at(-1)).toEqual({ type: "fetchMe", phase: "revalidate" });
  });
});
