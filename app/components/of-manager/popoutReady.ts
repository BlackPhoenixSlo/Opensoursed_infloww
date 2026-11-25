// An unknown id waits for the accounts read: a failed read could hide a watcher.
export const popoutReady = (id: string | null, knownIds: readonly string[], readOk: boolean): boolean =>
  !id || knownIds.includes(id) || readOk;
