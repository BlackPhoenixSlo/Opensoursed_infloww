"use client";

import { createContext, createElement, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

export type ReportPageCreator = (owner: symbol, accountId: string | null | undefined) => void;

const ReportContext = createContext<ReportPageCreator | null>(null);
const AppCreatorContext = createContext<string | null | undefined>(undefined);

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

export function useAppCreator(): string | null {
  const v = useContext(AppCreatorContext);
  if (v === undefined) throw new Error("useAppCreator needs a <PageCreatorProvider> above it");
  return v;
}

export function usePageCreator(accountId: string | null | undefined) {
  const report = useContext(ReportContext);
  const [owner] = useState(() => Symbol("page-creator"));
  useEffect(() => { report?.(owner, accountId); }, [report, owner, accountId]);
  useEffect(() => () => report?.(owner, undefined), [report, owner]);
}
