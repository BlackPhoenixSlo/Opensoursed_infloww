"use client";


import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useScope, useScopeHydrated } from "@/contexts/ScopeContext";
import { useAccounts } from "@/hooks/useAccounts";
import { lazyModule, useLazyModule } from "@/lib/lazyModule";
import { firstPage, isPlatformPage, platformOfPath } from "@/lib/nav";
import {
  accountPlatform, foreignCreator, getPlatform, hasSession, onPlatformChange, platformRow, setPlatform, usePlatform,
} from "@/lib/platform";

const loadAddCreatorModal = () => import("@/components/setup/AddCreatorModal").then((m) => m.default);
type AddCreatorModalType = Awaited<ReturnType<typeof loadAddCreatorModal>>;
// Lazy: the Add creator flow (~47 KB) is only needed after "Log in"; not next/dynamic, whose Suspense reveal shows a blank ~300 ms.
const creatorFlow = lazyModule(() => import("@/components/setup/creatorFlow"));

export const LOAD_FAILED_LINE = "Couldn't load the login — reload the page.";

export function PlatformSync() {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const { data, isSuccess, isPlaceholderData } = useAccounts();
  const accounts = data?.accounts;
  const { scope, setScope } = useScope();
  const hydrated = useScopeHydrated();
  const [owed, setOwed] = useState(true);
  const pathRef = useRef(pathname);
  useEffect(() => {
    pathRef.current = pathname;
  }, [pathname]);

  useEffect(
    () =>
      onPlatformChange((p) => {
        setOwed(true);
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
    if (!owed || !isSuccess || isPlaceholderData || !accounts || !hydrated) return;
    setOwed(false);
    if (scope.kind !== "model") return;
    if (foreignCreator(accounts, scope.accountId, getPlatform())) setScope({ kind: "all" }, { persist: false });
  }, [owed, isSuccess, isPlaceholderData, accounts, hydrated, scope, setScope]);

  return null;
}

export default function PlatformGate() {
  const pathname = usePathname() ?? "/";
  const platform = usePlatform();
  const accountsQ = useAccounts();

  const [dismissed, setDismissed] = useState<string | null>(null);
  const [login, setLogin] = useState<"idle" | "pending" | "failed">("idle");
  const [AddCreatorModal, setAddCreatorModal] = useState<AddCreatorModalType | null>(null);
  const accounts = accountsQ.data?.accounts;
  const row = platformRow(platform);
  const noSession =
    !!accounts && !accounts.some((a) => accountPlatform(a) === platform && a.has_session && !a.session_dead_at);
  const prompt = hasSession(row) && isPlatformPage(platform, pathname) && noSession && dismissed !== pathname;
  const load = useCallback(
    () => void loadAddCreatorModal().then(
      (m) => setAddCreatorModal(() => m),
      // A production (Turbopack) build keeps a failed chunk failed until reload (measured), hence "reload the page".
      () => setLogin((s) => (s === "pending" ? "failed" : s)),
    ),
    [],
  );
  useEffect(() => {
    if (prompt) load();
  }, [prompt, load]);
  const flow = useLazyModule(creatorFlow, prompt);
  const dismiss = () => { setLogin("idle"); setDismissed(pathname); };

  if (login === "pending" && AddCreatorModal) {
    return <AddCreatorModal extInstalled={null} at={row.relink} onClose={dismiss} />;
  }
  if (!prompt || !flow) return null;
  const { FlowButton, FlowModal, T } = flow;
  return (
    <FlowModal
      title={`${row.label} Login`}
      onClose={dismiss}
      footer={
        <>
          <FlowButton onClick={dismiss}>{T.cancel}</FlowButton>
          <FlowButton primary onClick={() => { setLogin("pending"); load(); }}>Log in</FlowButton>
        </>
      }
    >
      <p className="text-sm">{row.sessionPrompt}</p>
      {login === "failed" && !AddCreatorModal && <p role="alert" className="mt-2 text-sm text-err">{LOAD_FAILED_LINE}</p>}
    </FlowModal>
  );
}
