"use client";


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
import { stopBulkUnsends } from "@/components/settings/useBulkUnsend";
import { clearInline, takeInline } from "@/lib/inlineBoot";
import { forgetScreenBundles } from "@/lib/screenBundle";
import { forgetCreatorColsQueue } from "@/lib/creatorColsQueue";
import { forgetAll as forgetStatsLastGood } from "@/lib/ofMirrorStatsLastGood";
import { keptStorage } from "@/lib/chatSlots";
import { forgetScope } from "@/lib/screenEntry";
import { clearPersistedCache } from "@/lib/rqPersister";
import { forgetPush } from "@/lib/webPush";
import { isTwoFactorChallenge, postAuthJSON, TwoFactorRequired, type TwoFactorChallenge } from "@/lib/twoFactor";

import {
  decideUserSession, initialUserSession, probeAction,
  type AuthBanner, type BootStatus, type MeOutcome, type UserSessionAction,
} from "./userSessionReducer";

const IDENTITY_PRESERVE_KEYS = new Set<string>([
  "chatterly:theme",
  "chatterly:share_token",
  "chatterly:chunk-reload-attempted",
  "chatterly:chunk-reload-count",
  "chatterly:emoji_recents",
  "chatterly:chat-sort-mode",
  "chatterly:fan-drawer-default-open",
  "chatterly:compact-media",
]);

export interface ImpersonatingDTO {
  real_user_id: string;
  real_username: string;
}

export interface AuthedUserDTO {
  user_id: string;
  username: string;
  is_admin?: boolean;
  /** Present when the founder is currently viewing this user via the
   *  /admin/impersonate overlay. The relay restricts the session to
   *  read-only requests while this is non-null. */
  impersonating?: ImpersonatingDTO | null;
  created_at?: string | null;
}

interface UserContextValue {
  user: AuthedUserDTO | null;
  boot: BootStatus;
  banner: AuthBanner | null;
  formUp: boolean;
  loading: boolean;
  retry: () => void;
  login: (username: string, password: string) => Promise<AuthedUserDTO>;
  register: (username: string, password: string) => Promise<AuthedUserDTO>;
  logout: () => Promise<void>;
  startImpersonating: (userId: string, adminPassword: string) => Promise<void>;
  stopImpersonating: () => Promise<void>;
  clearUserLocally: () => void;
}

const UserContext = createContext<UserContextValue | null>(null);

export function clearIdentityMemory(): void {
  clearInline();
  forgetScreenBundles();
  clearSendStash();
  clearRefusedOffers();
  stopBulkUnsends();
  forgetStatsLastGood();
  forgetCreatorColsQueue();
}

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
        if (IDENTITY_PRESERVE_KEYS.has(k) || keptStorage(k)) continue;
        victims.push(k);
      }
      for (const k of victims) storage.removeItem(k);
    } catch { }
  }
  forgetScope();
  return clearPersistedCache();
}

function wipeIdentityCaches(queryClient: ReturnType<typeof useQueryClient>): Promise<void> {
  // Cancel first so in-flight onSuccess cannot re-seed the cache with the previous identity.
  try { queryClient.cancelQueries(); } catch { }
  try { queryClient.clear(); } catch { }
  clearIdentityMemory();
  const wiped = wipeIdentityStorage();
  try {
    if (typeof navigator !== "undefined" && "serviceWorker" in navigator) {
      navigator.serviceWorker.getRegistration().then((reg) => {
        const sw = reg?.active;
        // Closes the manual-snoop hole: the next user on this browser could read the previous user's cached images.
        if (sw) sw.postMessage({ type: "clear-cache" });
      }).catch(() => { });
    }
  } catch { }
  return wiped;
}

const ME_TIMEOUT_MS = 15_000;
const ME_SLOW_MS = 3_000;

async function readMe(): Promise<MeOutcome> {
  try {
    const inline = takeInline("/auth/me");
    const r = (inline && await inline) ?? await fetch("/auth/me", {
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
  const [session, setSession] = useState(initialUserSession);
  const sessionRef = useRef(initialUserSession);
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
          const slow = setTimeout(() => { if (gen === probeGen.current) send({ type: "probeSlow" }); }, ME_SLOW_MS);
          void readMe().then((o) => {
            clearTimeout(slow);
            if (gen === probeGen.current) send(probeAction(phase, o));
          });
          break;
        }
      }
    }
    setSession(state);
  }, [queryClient]);

  useEffect(() => {
    // In the effect, not a lazy useState: the server has no localStorage, so seeding first render would be a hydration mismatch.
    send({ type: "bootStart", snapshot: readAuthSnapshot() });
  }, [send]);

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

  const retry = useCallback(() => send({ type: "bootStart", snapshot: null }), [send]);

  const adoptAnswer = useCallback(
    (u: AuthedUserDTO | null) => send(u ? { type: "confirmed", user: u } : { type: "logout" }),
    [send],
  );

  const login = useCallback(async (username: string, password: string) => {
    const dto = await postAuthJSON<AuthedUserDTO | TwoFactorChallenge>("/auth/login", { username, password });
    if (isTwoFactorChallenge(dto)) throw new TwoFactorRequired(dto);
    void wipeIdentityCaches(queryClient);
    send({ type: "confirmed", user: dto });
    return dto;
  }, [queryClient, send]);

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
    forgetPush();
    try { await postAuthJSON<unknown>("/auth/logout", {}); } catch { }
    const wiped = wipeIdentityCaches(queryClient);
    send({ type: "logout" });
    await wiped;
    if (typeof window !== "undefined") {
      // replace, not assign: back must not return to the signed-in URL.
      window.location.replace("/");
    }
  }, [queryClient, send]);

  const startImpersonating = useCallback(
    async (userId: string, adminPassword: string) => {
      const dto = await postAuthJSON<{ impersonating: { user_id: string; username: string } }>(
        "/admin/impersonate",
        { user_id: userId, admin_password: adminPassword },
      );
      void wipeIdentityCaches(queryClient);
      const me = await readMe();
      if (me.type === "netError") throw me.error;
      if (me.type === "answered") {
        adoptAnswer(me.user);
      } else {
        send({
          // Not confirmed: this identity was never confirmed by the server, so no snapshot may paint it.
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
    } catch { }
    void wipeIdentityCaches(queryClient);
    const me = await readMe();
    if (me.type === "answered") adoptAnswer(me.user);
  }, [queryClient, adoptAnswer]);

  const { user, boot, banner, formUp } = session;
  const value = useMemo<UserContextValue>(
    () => ({
      user, boot, banner, formUp, loading: boot === "probing" && !user, retry,
      login, register, logout, startImpersonating, stopImpersonating, clearUserLocally,
    }),
    [user, boot, banner, formUp, retry, login, register, logout, startImpersonating, stopImpersonating, clearUserLocally],
  );

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>;
}

export function useUser(): UserContextValue {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error("useUser called outside <UserProvider>");
  return ctx;
}

export function useOptionalUser(): UserContextValue | null {
  return useContext(UserContext);
}
