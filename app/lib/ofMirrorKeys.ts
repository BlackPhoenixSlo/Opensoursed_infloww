import type { QueryClient } from "@tanstack/react-query";

export const MIRROR = "of-mirror-data";

export function mirrorKey(accountId: string | null, path?: string) {
  return path === undefined ? [MIRROR, accountId] : [MIRROR, accountId, path];
}

export function mirrorUnder(accountId: string | null, test: (path: unknown) => boolean) {
  return ({ queryKey: k }: { queryKey: readonly unknown[] }) => k[0] === MIRROR && k[1] === accountId && test(k[2]);
}

export function afterChatWrite(qc: QueryClient, accountId: string | null) {
  return Promise.all([qc.invalidateQueries({ queryKey: mirrorKey(accountId) }), qc.invalidateQueries({ queryKey: ["chats"] })]);
}

export function afterProfileWrite(qc: QueryClient, accountId: string | null) {
  return Promise.all([qc.invalidateQueries({ queryKey: ["of-me", accountId] }), qc.invalidateQueries({ queryKey: ["of-settings"] })]);
}
