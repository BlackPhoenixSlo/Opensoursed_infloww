"use client";

/**
 * The app's model: the page's own Creator pick, else the scope switcher.
 *
 * Some pages pick their Creator locally instead of through the app's scope
 * switcher — Vault Pro, Scripts, Smart messages and every PageFrame page do it
 * in `CreatorRail` (components/shell), which reports its value here
 * (`usePageCreator`). While such a page is on screen its pick IS the app's
 * model; leaving the page hands back to the scope switcher (all models →
 * null). `useAppCreator()` reads the result — the help bot's
 * AssistantProvider (components/assistant) focuses on it. A neutral module,
 * so the shell and the assistant import a context, not each other. Mounted
 * in app/layout.tsx inside AuthGate (the scope resolves there).
 */
import { createContext, createElement, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { useScope } from "@/contexts/ScopeContext";

/** An account id, null for a page's "All" row, undefined for no pick (anymore). */
export type ReportPageCreator = (owner: symbol, accountId: string | null | undefined) => void;

const ReportContext = createContext<ReportPageCreator | null>(null);
const AppCreatorContext = createContext<string | null | undefined>(undefined);

/** Owns the page pick: the last reporter's value until it reports undefined
 *  (or unmounts); another page's leftover never clears a newer one. */
export function PageCreatorProvider({ children }: { children: ReactNode }) {
  const { accountId: scopedId } = useScope();
  const [page, setPage] = useState<{ owner: symbol; accountId: string | null } | null>(null);
  const report = useCallback<ReportPageCreator>((owner, accountId) => setPage((cur) => {
    if (accountId === undefined) return cur?.owner === owner ? null : cur;
    return cur?.owner === owner && cur.accountId === accountId ? cur : { owner, accountId };
  }), []);
  const app = page ? page.accountId : scopedId;
  return createElement(ReportContext.Provider, { value: report },
    createElement(AppCreatorContext.Provider, { value: app }, children));
}

/** The app's model: the page's pick, else the scope switcher's (null = all models). */
export function useAppCreator(): string | null {
  const v = useContext(AppCreatorContext);
  if (v === undefined) throw new Error("useAppCreator needs a <PageCreatorProvider> above it");
  return v;
}

/** Report the page's pick: an account id, null for its "All" row, undefined
 *  for none yet. No-op with no provider above (page tests). */
export function usePageCreator(accountId: string | null | undefined) {
  const report = useContext(ReportContext);
  const [owner] = useState(() => Symbol("page-creator"));
  useEffect(() => { report?.(owner, accountId); }, [report, owner, accountId]);
  useEffect(() => () => report?.(owner, undefined), [report, owner]);
}
