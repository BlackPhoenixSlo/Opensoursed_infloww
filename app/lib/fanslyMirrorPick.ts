"use client";

import { useSearchParams } from "next/navigation";

import { useAccounts, usePlatformAccounts } from "@/hooks/useAccounts";
import type { AccountMeta } from "@/lib/relay";
import { liveSession } from "@/lib/sessionConnectivity";

export type FanslyPick =
  | { kind: "picked"; accountId: string }
  | { kind: "standIn"; accountId: string }
  | { kind: "none" }
  | { kind: "loading" };

type Known = Pick<AccountMeta, "id" | "has_session" | "session_dead_at">;

export function fanslyPick<A extends Known>(known: readonly A[] | undefined, creatorParam: string | null): { live: A[]; pick: FanslyPick } {
  if (!known) return { live: [], pick: { kind: "loading" } };
  const live = known.filter(liveSession);
  if (creatorParam && live.some((a) => a.id === creatorParam)) return { live, pick: { kind: "picked", accountId: creatorParam } };
  return { live, pick: live[0] ? { kind: "standIn", accountId: live[0].id } : { kind: "none" } };
}

export function useFanslyPick() {
  const creatorParam = useSearchParams()?.get("creator") ?? null;
  const accounts = useAccounts();
  const known = usePlatformAccounts("fansly");
  const { live, pick } = fanslyPick(accounts.isSuccess ? known : accounts.isError ? [] : undefined, creatorParam);
  return { failed: accounts.isError, live, pick, shown: pick.kind === "picked" || pick.kind === "standIn" ? pick.accountId : null };
}
