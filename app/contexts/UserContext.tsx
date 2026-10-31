"use client";

/**
 * UserContext — "is anyone signed in" state for the friend-auth layer.
 *
 * Fetches /auth/me on mount, painting the last confirmed user meanwhile
 * (lib/authSnapshot.ts). While `loading` is true (no snapshot to paint) the
 * gate shows no shell (avoids a flash of the picker or app surface). When the
 * fetch returns:
 *   - user object → render children
 *   - null → redirect to /login (handled by the gate component)
 *   - unreachable (boot only) → a retry screen, not the sign-in form
 *
 * Login + logout are routed through here so consumers (TopNav, landing
 * form) don't have to know about the session cookie or refetch flow.
 *
 * Auth here is intentionally separate from the EmployeeContext picker
 * (which gates X-Employee-Id for audit). Order in providers.tsx:
 *   UserProvider → EmployeeProvider → ScopeProvider.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";

import { readAuthSnapshot, writeAuthSnapshot } from "@/lib/authSnapshot";
import { clearSendStash } from "@/lib/sendStash";
import { clearRefusedOffers } from "@/components/chat/refusedOffers";
import { clearPersistedCache } from "@/lib/rqPersister";
import { isTwoFactorChallenge, postAuthJSON, TwoFactorRequired, type TwoFactorChallenge } from "@/lib/twoFactor";

import {
  decideUserSession, initialUserSession, probeAction, type BootStatus, type MeOutcome, type UserSessionAction,
} from "./userSessionReducer";

// localStorage / sessionStorage keys to PRESERVE across identity switches.
// Anything else under the `chatterly:` or `chatterly-` prefix is wiped on
// every login / logout / register so a new identity boots with a fresh
// per-account state — vault picker MRU, scope selection, persisted React
// Query cache, notification history, etc.
//
// The previous wipe was a narrow two-key list; that left vault-state /
// scope / notification keys behind, which surfaced as a "not your account"
// 403 from the relay when the previous user's account_id sneaked into a
// fetch via stale cache. Aggressive identity-switch wiping closes that.
const IDENTITY_PRESERVE_KEYS = new Set<string>([
  "chatterly:theme",                            // UI preference
  "chatterly:share_token",                      // share-link gate
  "chatterly:chunk-reload-attempted",           // chunk-load retry guard
  "chatterly:chunk-reload-count",
  "chatterly:lockedText-default-changed-seen",  // one-time notice
  "chatterly:emoji_recents",                    // UI preference
  "chatterly:chat-sort-mode",                   // UI preference
  "chatterly:fan-drawer-default-open",          // UI preference
  "chatterly:compact-media",                    // UI preference
]);

export interface ImpersonatingDTO {
  real_user_id: string;
  real_username: string;
}

export interface AuthedUserDTO {
  user_id: string;
  username: string;
  /** Master role. Used ONLY to decide whether a founder-only surface is worth
   *  drawing — the relay gates every one of them server-side regardless. While
   *  impersonating this is the impersonated user's role, so the founder stops
   *  seeing the server's house-key panel while wearing an agency's identity. */
  is_admin?: boolean;
  /** Present when the founder is currently viewing this user via the
   *  /admin/impersonate overlay. The relay restricts the session to
   *  read-only requests while this is non-null. */
  impersonating?: ImpersonatingDTO | null;
  /** When this user registered (ISO, UTC); the free trial counts from it. */
  created_at?: string | null;
}

interface UserContextValue {
  user: AuthedUserDTO | null;
  /** Where the boot /auth/me is (userSessionReducer.ts); `unreachable` is the
   *  gate's retry screen, not the sign-in form. */
  boot: BootStatus;
  /** The boot probe is in flight and no warm-boot snapshot is painted. */
  loading: boolean;
  /** From `unreachable`: run the boot again; a no-op otherwise. */
  retry: () => void;
  /** Sign in with a known username/password. Throws RelayError on 4xx, and
   *  TwoFactorRequired when the account has 2FA on (lib/twoFactor.ts). */
  login: (username: string, password: string) => Promise<AuthedUserDTO>;
  /** Register a new friend. Throws on conflict / validation error. */
  register: (username: string, password: string) => Promise<AuthedUserDTO>;
  logout: () => Promise<void>;
  /** Founder-only: start viewing as another user. Wipes all caches so
   *  the next render reads fresh data for the target. */
  startImpersonating: (userId: string, adminPassword: string) => Promise<void>;
  /** Founder-only: clear the impersonate cookie + caches and re-fetch
   *  the founder's own /auth/me. */
  stopImpersonating: () => Promise<void>;
  /** Local-only identity flip: clears caches + sets user=null without
   *  hitting /auth/logout. Used by the chatter-login flow when
   *  transitioning principals on the same browser without two round-
   *  trips (logout, then chatter-login). */
  clearUserLocally: () => void;
}

const UserContext = createContext<UserContextValue | null>(null);

/** Drop the previous identity's in-memory stores: unsent messages (a send
 *  waiting on its files) and refused schedules' drafts. Shared between
 *  UserContext + ChatterContext, as `wipeIdentityStorage` is. */
export function clearIdentityMemory(): void {
  clearSendStash();
  clearRefusedOffers();
}

/** Wipe every chatterly storage key not on the preserve allowlist, and the
 *  persisted React Query snapshot. Shared between UserContext + ChatterContext
 *  so both principals get the same aggressive wipe on identity switch.
 *  Resolves once the snapshot delete has committed (await it before a hard
 *  navigation); never rejects. */
export function wipeIdentityStorage(): Promise<void> {
  for (const storage of [
    typeof window !== "undefined" ? window.localStorage : null,
    typeof window !== "undefined" ? window.sessionStorage : null,
  ]) {
    if (!storage) continue;
    try {
      const victims: string[] = [];
      for (let i = 0; i < storage.length; i++) {
        const k = storage.key(i);
        if (!k) continue;
        if (!k.startsWith("chatterly:") && !k.startsWith("chatterly-")) continue;
        if (IDENTITY_PRESERVE_KEYS.has(k)) continue;
        victims.push(k);
      }
      for (const k of victims) storage.removeItem(k);
    } catch { /* safari private / quota — best effort */ }
  }
  // The persisted React Query snapshot lives in IndexedDB, out of the sweep's
  // reach. The clear also cancels a throttled write still pending, so the
  // snapshot can't be re-stamped with what the cache held before the wipe.
  return clearPersistedCache();
}

function wipeIdentityCaches(queryClient: ReturnType<typeof useQueryClient>): Promise<void> {
  // Cancel in-flight queries first so their `onSuccess` doesn't race the
  // clear and re-seed cache with previous-identity data after we've
  // wiped. cancelQueries returns a promise; we don't await — synchronous
  // clear() below is sufficient because RQ marks cancelled fetches as
  // such, and dehydration only persists successes.
  try { queryClient.cancelQueries(); } catch { /* ignore */ }
  // Drop in-memory React Query cache (everything, including non-persisted
  // keys — a stale chat list from the previous user is just as wrong as
  // a stale account list).
  try { queryClient.clear(); } catch { /* ignore */ }
  // Unsent messages and refused schedules are the previous identity's.
  clearIdentityMemory();
  // Wipe identity-bound localStorage + sessionStorage. Anything under the
  // `chatterly:` / `chatterly-` namespace that isn't a preserved UI
  // preference dies here — vault picker state, scope selection,
  // notification history, persisted RQ cache, etc.
  const wiped = wipeIdentityStorage();
  // Fire-and-forget message to the image SW. It deletes the whole
  // chatterly-img-v3 Cache Storage bucket. SW is prod-only and may not
  // be registered (dev / insecure origin / first paint before register
  // resolves) — silently no-op in those cases.
  try {
    if (typeof navigator !== "undefined" && "serviceWorker" in navigator) {
      navigator.serviceWorker.getRegistration().then((reg) => {
        const sw = reg?.active;
        if (sw) sw.postMessage({ type: "clear-cache" });
      }).catch(() => { /* ignore */ });
    }
  } catch { /* ignore */ }
  return wiped;
}

/** How long a GET /auth/me may hang before it counts as unreachable: a hung
 *  boot probe would otherwise hold the gate shut (and every revalidation off). */
const ME_TIMEOUT_MS = 15_000;

/** One GET /auth/me, as what it ended in. Never rejects. */
async function readMe(): Promise<MeOutcome> {
  try {
    const r = await fetch("/auth/me", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(ME_TIMEOUT_MS),
    });
    if (!r.ok) return { type: "refused", status: r.status };
    const body = (await r.json()) as AuthedUserDTO | null;
    return { type: "answered", user: body && body.user_id ? body : null };
  } catch (error) {
    return { type: "netError", error };
  }
}

export function UserProvider({ children }: { children: React.ReactNode }) {
  // The session's rules live in userSessionReducer.ts; this is the shell. The
  // state is mirrored in a ref so two events in one tick (two focus events)
  // see each other — the in-flight guard depends on it.
  const [session, setSession] = useState(initialUserSession);
  const sessionRef = useRef(initialUserSession);
  /** Bumped on `dropProbes`; a probe from an older generation is dropped. */
  const probeGen = useRef(0);
  const queryClient = useQueryClient();

  const send = useCallback(function send(action: UserSessionAction) {
    const { state, effects } = decideUserSession(sessionRef.current, action);
    sessionRef.current = state;
    for (const fx of effects) {
      switch (fx.type) {
        case "wipeCaches": void wipeIdentityCaches(queryClient); break;
        case "snapshot": writeAuthSnapshot(fx.user); break;
        case "dropProbes": probeGen.current += 1; break;
        case "fetchMe": {
          const gen = probeGen.current;
          const phase = fx.phase;
          void readMe().then((o) => {
            if (gen === probeGen.current) send(probeAction(phase, o));
          });
          break;
        }
      }
    }
    setSession(state);
  }, [queryClient]);

  useEffect(() => {
    // Optimistic open. The gate below us renders nothing while `loading`
    // is true, which held back every persisted query cache in the app for
    // one full /auth/me round-trip on EVERY reload. A snapshot of the last
    // confirmed principal lets the shell (and the caches under it) paint
    // now; the probe still runs and still decides.
    //
    // Deliberately inside the effect rather than a lazy useState: the
    // server renders with no localStorage, so seeding first render from a
    // snapshot would be a hydration mismatch. This costs one frame after
    // hydration instead of a network round-trip.
    // A re-run (StrictMode) re-probes while the boot is in flight; once settled it is a no-op.
    send({ type: "bootStart", snapshot: readAuthSnapshot() });
  }, [send]);

  // Re-validate /auth/me when the tab regains focus / becomes visible so a
  // stale impersonation overlay (e.g. another tab stopped impersonating, or
  // the cookie expired) self-corrects without a full reload. It only fires
  // on real user focus/visibility events; the initial load stays owned by
  // the boot effect above.
  useEffect(() => {
    const hidden = () => typeof document !== "undefined" && document.visibilityState === "hidden";
    const revalidate = () => send({ type: "revalidateStart", hidden: hidden() });
    const onVisibility = () => {
      if (typeof document !== "undefined" && document.visibilityState === "visible") revalidate();
    };
    window.addEventListener("focus", revalidate);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("focus", revalidate);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [send]);

  // The retry screen's button: the boot again, without the snapshot (the gate
  // waits on the answer). A no-op once the boot settled.
  const retry = useCallback(() => send({ type: "bootStart", snapshot: null }), [send]);

  /** What a flow's /auth/me answered: that user, or nobody signed in. */
  const adoptAnswer = useCallback(
    (u: AuthedUserDTO | null) => send(u ? { type: "confirmed", user: u } : { type: "logout" }),
    [send],
  );

  const login = useCallback(async (username: string, password: string) => {
    const dto = await postAuthJSON<AuthedUserDTO | TwoFactorChallenge>("/auth/login", { username, password });
    // 2FA on: no cookie yet; the form asks for the code (TwoFactorStep).
    if (isTwoFactorChallenge(dto)) throw new TwoFactorRequired(dto);
    // Wipe any cache from the previous identity BEFORE flipping the user
    // state — otherwise the in-flight render reads the previous user's
    // data through the next paint.
    void wipeIdentityCaches(queryClient);
    send({ type: "confirmed", user: dto });
    return dto;
  }, [queryClient, send]);

  /** Raw cache wipe + setUser(null). Used by the chatter-login flow when
   *  it needs to flip identities without going through the network logout
   *  (the chatter is about to sign in via /chatter/login on the next call
   *  — we just want the local User state cleared so AuthGate doesn't keep
   *  rendering as the owner). */
  const clearUserLocally = useCallback(() => {
    void wipeIdentityCaches(queryClient);
    send({ type: "logout" });
  }, [queryClient, send]);

  const register = useCallback(async (username: string, password: string) => {
    const dto = await postAuthJSON<AuthedUserDTO>("/auth/register", { username, password });
    void wipeIdentityCaches(queryClient);
    send({ type: "confirmed", user: dto });
    return dto;
  }, [queryClient, send]);

  const logout = useCallback(async () => {
    try { await postAuthJSON<unknown>("/auth/logout", {}); } catch { /* best effort */ }
    const wiped = wipeIdentityCaches(queryClient);
    send({ type: "logout" });
    // The snapshot delete must commit before the navigation tears the page down.
    await wiped;
    // Hard navigate so AuthGate evaluates from scratch. /auth/logout
    // now clears the chatter cookie defensively too, so a chatter ghost
    // could otherwise linger in cache (UserContext doesn't refetch
    // /auth/me after mount, ChatterContext's meQ races against the
    // cache wipe). A `.replace()` rather than `.assign()` so the back
    // button doesn't return to the signed-in URL.
    if (typeof window !== "undefined") {
      window.location.replace("/");
    }
  }, [queryClient, send]);

  const startImpersonating = useCallback(
    async (userId: string, adminPassword: string) => {
      // Set the overlay first; the relay validates admin_password and
      // throws on 403/404 before any cookie is set. Then wipe caches —
      // the next /auth/me + every downstream fetch resolves to the
      // impersonated user.
      const dto = await postAuthJSON<{ impersonating: { user_id: string; username: string } }>(
        "/admin/impersonate",
        { user_id: userId, admin_password: adminPassword },
      );
      void wipeIdentityCaches(queryClient);
      // Re-fetch /auth/me so `user.impersonating` flips on for the banner
      // without waiting for the next reload. Unreachable: the caller shows
      // the error (the overlay cookie is already set; the next reload shows it).
      const me = await readMe();
      if (me.type === "netError") throw me.error;
      if (me.type === "answered") {
        adoptAnswer(me.user);
      } else {
        // /auth/me hiccup is benign — UI will resync on next route change.
        // Fall back to a synthesized stub so the banner still renders.
        // NOT `confirmed`: this identity was never confirmed by
        // the server, and a snapshot of it would paint an overlay that
        // may already be gone on the next boot.
        send({
          type: "unconfirmed",
          user: { user_id: dto.impersonating.user_id, username: dto.impersonating.username },
        });
      }
    },
    [queryClient, send, adoptAnswer],
  );

  const stopImpersonating = useCallback(async () => {
    try {
      await fetch("/admin/impersonate", {
        method: "DELETE",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
    } catch { /* best-effort */ }
    void wipeIdentityCaches(queryClient);
    // Re-fetch /auth/me so the founder's real identity is back in `user`;
    // a refusal or an unreachable relay keeps the current one.
    const me = await readMe();
    if (me.type === "answered") adoptAnswer(me.user);
  }, [queryClient, adoptAnswer]);

  const { user, boot } = session;
  const value = useMemo<UserContextValue>(
    () => ({
      user, boot, loading: boot === "probing" && !user, retry,
      login, register, logout, startImpersonating, stopImpersonating, clearUserLocally,
    }),
    [user, boot, retry, login, register, logout, startImpersonating, stopImpersonating, clearUserLocally],
  );

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>;
}

export function useUser(): UserContextValue {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser called outside <UserProvider>");
  return ctx;
}

/** Non-throwing variant: returns null outside <UserProvider> instead of
 *  throwing. For hooks that only want the user *if one is mounted* (e.g. a
 *  per-principal cache key) and must stay usable in provider-less contexts. */
export function useOptionalUser(): UserContextValue | null {
  return useContext(UserContext);
}
