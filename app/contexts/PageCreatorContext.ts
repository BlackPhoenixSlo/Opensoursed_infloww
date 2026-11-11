"use client";

/**
 * The app's model: the Creator picker on screen, else all models (null).
 *
 * Every creator picker reports its value here (`usePageCreator`): a local one
 * (`CreatorColumn` with `onChange` — Vault Pro, Scripts, Smart messages, every
 * CreatorRail/PageFrame page) and the scope switcher's (OF Manager's column,
 * ScopeSelect, Messages Pro's CreatorTabs). A page with no picker (Dashboard,
 * Statements, Settings…) is agency-wide, so the app's model is all models
 * there even when a single-Creator scope is saved — the saved scope is
 * invisible on such a page. `useAppCreator()` reads the result — the help bot's
 * AssistantProvider (components/assistant) focuses on it. A neutral module,
 * so the shell and the assistant import a context, not each other. Mounted
 * in app/layout.tsx.
 */
import { createContext, createElement, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

/** An account id, null for a page's "All" row, undefined for no pick (anymore). */
export type ReportPageCreator = (owner: symbol, accountId: string | null | undefined) => void;

const ReportContext = createContext<ReportPageCreator | null>(null);
const AppCreatorContext = createContext<string | null | undefined>(undefined);

/** Owns the page pick: the last reporter's value until it reports undefined
 *  (or unmounts); another page's leftover never clears a newer one. */
export function PageCreatorProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<{ owner: symbol; accountId: string | null } | null>(null);
  const report = useCallback<ReportPageCreator>((owner, accountId) => setPage((cur) => {
    if (accountId === undefined) return cur?.owner === owner ? null : cur;
    return cur?.owner === owner && cur.accountId === accountId ? cur : { owner, accountId };
  }), []);
  const app = page ? page.accountId : null;
  return createElement(ReportContext.Provider, { value: report },
    createElement(AppCreatorContext.Provider, { value: app }, children));
}

/** The app's model: the on-screen picker's, else null (all models). */
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
