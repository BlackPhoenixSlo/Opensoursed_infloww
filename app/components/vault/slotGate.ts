export function makeSlotGate(limit: number) {
  const holding = new Set<() => void>();
  const waiting: (() => void)[] = [];
  return {
    acquire(grant: () => void) {
      if (holding.size < limit) {
        holding.add(grant);
        grant();
        return;
      }
      waiting.push(grant);
    },
    // Release is exact per grant token: a counter let a second release free a slot nobody gave back and the cap grew.
    release(grant: () => void) {
      const queued = waiting.indexOf(grant);
      if (queued >= 0) {
        waiting.splice(queued, 1);
        return;
      }
      if (!holding.delete(grant)) return;
      const next = waiting.shift();
      if (next) {
        holding.add(next);
        next();
      }
    },
  };
}
