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
import { useEffect, useRef, useState } from "react";

import AddCreatorModal from "@/components/setup/AddCreatorModal";
import { FlowButton, FlowModal, T } from "@/components/setup/creatorFlow";
import { useScope } from "@/contexts/ScopeContext";
import { useAccounts } from "@/hooks/useAccounts";
import { firstPage, isPlatformPage, platformOfPath } from "@/lib/nav";
import {
  accountPlatform, getPlatform, onPlatformChange, setPlatform, usePlatform, type Platform,
} from "@/lib/platform";

export const FANSLY_LOGIN_TITLE = "Fansly Login";
/** components-view0042, as the brief quotes it (the key's locale chunk is not on disk). */
export const FANSLY_LOGIN_LINE = "Please login Fansly";

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
  const [linking, setLinking] = useState(false);
  const accounts = accountsQ.data?.accounts;
  const noFanslySession =
    !!accounts && !accounts.some((a) => accountPlatform(a) === "fansly" && a.has_session && !a.session_dead_at);
  const prompt = platform === "fansly" && isPlatformPage("fansly", pathname) && noFanslySession && dismissed !== pathname;

  if (linking) {
    return <AddCreatorModal extInstalled={null} at="fansly" onClose={() => { setLinking(false); setDismissed(pathname); }} />;
  }
  if (!prompt) return null;
  return (
    <FlowModal
      title={FANSLY_LOGIN_TITLE}
      onClose={() => setDismissed(pathname)}
      footer={
        <>
          <FlowButton onClick={() => setDismissed(pathname)}>{T.cancel}</FlowButton>
          <FlowButton primary onClick={() => setLinking(true)}>Log in</FlowButton>
        </>
      }
    >
      <p className="text-sm">{FANSLY_LOGIN_LINE}</p>
    </FlowModal>
  );
}
