/** The OF mirror's query keys and the refreshes its writes share. */
import type { QueryClient } from "@tanstack/react-query";

/** Every mirror read's key starts with it (ofMirrorData's mirrorQuery and its paged reads). */
export const MIRROR = "of-mirror-data";

/** A model's mirror reads (`[MIRROR, accountId]`, a prefix), or the one for `path` (mirrorQuery's key). */
export function mirrorKey(accountId: string | null, path?: string) {
  return path === undefined ? [MIRROR, accountId] : [MIRROR, accountId, path];
}

/** invalidateQueries' predicate: `accountId`'s mirror reads whose path passes `test`. */
export function mirrorUnder(accountId: string | null, test: (path: unknown) => boolean) {
  return ({ queryKey: k }: { queryKey: readonly unknown[] }) => k[0] === MIRROR && k[1] === accountId && test(k[2]);
}

/** After a chat write: the model's mirror reads and Messages Pro's chat lists. */
export function afterChatWrite(qc: QueryClient, accountId: string | null) {
  return Promise.all([qc.invalidateQueries({ queryKey: mirrorKey(accountId) }), qc.invalidateQueries({ queryKey: ["chats"] })]);
}

/** After a profile write: the model's users/me and every settings read. */
export function afterProfileWrite(qc: QueryClient, accountId: string | null) {
  return Promise.all([qc.invalidateQueries({ queryKey: ["of-me", accountId] }), qc.invalidateQueries({ queryKey: ["of-settings"] })]);
}
