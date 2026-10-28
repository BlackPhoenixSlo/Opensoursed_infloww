"use client";

/**
 * The shell's platform rules that live outside the selector.
 *
 * PlatformSync, in every window (Messages Pro too):
 *   - Route-driven switch: a page only one platform shows switches the shell
 *     to that platform (an OnlyFans bookmark opened in Fansly mode, a Fansly
 *     Manager link), as Infloww's layout does on a route change
 *     (`DesignLayout`, index.9f50f370.js @11131400).
 *   - On any switch (the selector, a route, another window's `storage`): a
 *     page only the other platform shows goes to the new platform's first page
 *     (`getFirstMenu`, @10736265), and a scope on a creator of the other
 *     platform drops to All. The scope waits for the account list and drops
 *     only a creator known to be on the other platform. No loop: the first
 *     page is never the other platform's, so landing there switches nothing.
 *
 * PlatformGate, outside Messages Pro:
 *   - "Fansly Login": in Fansly mode, on a Fansly page, with no Fansly account
 *     holding a live session, a prompt to link one. Infloww opens its global
 *     Fansly login window (`FanslyLogin`, @10996472) when a Fansly page has
 *     no session; ours opens the Add creator flow at the Fansly paste step.
 *     Cancel hides it for this page.
 */

import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { FlowButton, FlowModal, T } from "@/components/setup/creatorFlow";
import { useScope } from "@/contexts/ScopeContext";
import { useAccounts } from "@/hooks/useAccounts";
import { firstPage, isPlatformPage, platformOfPath } from "@/lib/nav";
import {
  accountPlatform, getPlatform, onPlatformChange, setPlatform, usePlatform, type Platform,
} from "@/lib/platform";

// Lazy: this gate is in every page's shell (AppShell), but the Add creator flow
// (the cURL paste card and its parser, ~47 KB) only opens after a "Log in"
// click on a Fansly page with no session. A static import put it in every
// first load. The prompt loads it, and stays up until it has, so "Log in"
// swaps one modal for the other in one render. Not next/dynamic: its first
// render suspends even on a loaded chunk, and React shows the empty fallback
// for ~300 ms (its Suspense reveal throttle), a blank screen between the two.
const loadAddCreatorModal = () => import("@/components/setup/AddCreatorModal").then((m) => m.default);
type AddCreatorModalType = Awaited<ReturnType<typeof loadAddCreatorModal>>;

export const FANSLY_LOGIN_TITLE = "Fansly Login";
/** components-view0042, as the brief quotes it (the key's locale chunk is not on disk). */
export const FANSLY_LOGIN_LINE = "Please login Fansly";
export const LOAD_FAILED_LINE = "Couldn't load the login — reload the page.";

export function PlatformSync() {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const accounts = useAccounts().data?.accounts;
  const { scope, setScope } = useScope();
  // The platform a switch left the scope to check against, until the account list answers.
  const [owed, setOwed] = useState<Platform | null>(null);
  const pathRef = useRef(pathname);
  // Declared first so the route effect below already sees the new path.
  useEffect(() => {
    pathRef.current = pathname;
  }, [pathname]);

  useEffect(
    () =>
      onPlatformChange((p) => {
        setOwed(p);
        const owner = platformOfPath(pathRef.current);
        if (owner && owner !== p) router.push(firstPage(p));
      }),
    [router],
  );

  useEffect(() => {
    const owner = platformOfPath(pathname);
    if (owner && owner !== getPlatform()) setPlatform(owner);
  }, [pathname]);

  useEffect(() => {
    if (!owed || !accounts) return;
    setOwed(null);
    if (owed !== getPlatform() || scope.kind !== "model") return;
    const a = accounts.find((x) => x.id === scope.accountId);
    if (a && accountPlatform(a) !== owed) setScope({ kind: "all" });
  }, [owed, accounts, scope, setScope]);

  return null;
}

export default function PlatformGate() {
  const pathname = usePathname() ?? "/";
  const platform = usePlatform();
  const accountsQ = useAccounts();

  const [dismissed, setDismissed] = useState<string | null>(null);
  // "pending": a "Log in" waits for the flow to load. "failed": that load failed (likely the chunk is gone after
  // a deploy), so the prompt shows one line until a load lands.
  const [login, setLogin] = useState<"idle" | "pending" | "failed">("idle");
  const [AddCreatorModal, setAddCreatorModal] = useState<AddCreatorModalType | null>(null);
  const accounts = accountsQ.data?.accounts;
  const noFanslySession =
    !!accounts && !accounts.some((a) => accountPlatform(a) === "fansly" && a.has_session && !a.session_dead_at);
  const prompt = platform === "fansly" && isPlatformPage("fansly", pathname) && noFanslySession && dismissed !== pathname;
  // A failed load fails only a pending "Log in": the prompt's preload, or a "Log in" already
  // cancelled, fails silently. The failed "Log in" leaves the prompt up with the error line.
  // "Log in" imports again, but a production (Turbopack) build keeps a failed chunk failed until
  // the page reloads (measured; `next dev` fetches it again), hence the line's "reload the page".
  const load = useCallback(
    () => void loadAddCreatorModal().then(
      (m) => setAddCreatorModal(() => m),
      () => setLogin((s) => (s === "pending" ? "failed" : s)),
    ),
    [],
  );
  useEffect(() => {
    if (prompt) load();
  }, [prompt, load]);
  // Every close path drops a pending "Log in", so a load that lands later opens nothing.
  const dismiss = () => { setLogin("idle"); setDismissed(pathname); };

  if (login === "pending" && AddCreatorModal) {
    return <AddCreatorModal extInstalled={null} at="fansly" onClose={dismiss} />;
  }
  if (!prompt) return null;
  return (
    <FlowModal
      title={FANSLY_LOGIN_TITLE}
      onClose={dismiss}
      footer={
        <>
          <FlowButton onClick={dismiss}>{T.cancel}</FlowButton>
          <FlowButton primary onClick={() => { setLogin("pending"); load(); }}>Log in</FlowButton>
        </>
      }
    >
      <p className="text-sm">{FANSLY_LOGIN_LINE}</p>
      {login === "failed" && !AddCreatorModal && <p role="alert" className="mt-2 text-sm text-err">{LOAD_FAILED_LINE}</p>}
    </FlowModal>
  );
}
