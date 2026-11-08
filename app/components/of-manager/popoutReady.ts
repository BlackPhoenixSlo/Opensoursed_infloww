/** A Pop-out's `?account=<id>` may be applied: no id, an id known as a Creator or a watcher, or any id once the
 *  accounts read succeeded (an unknown id waits for it: a failed read could hide a watcher). */
export const popoutReady = (id: string | null, knownIds: readonly string[], readOk: boolean): boolean =>
  !id || knownIds.includes(id) || readOk;
