/** The image slot gate (moved out of `VaultPackPickerModal`): a hard in-flight cap with a FIFO queue. */

/** A module-wide gate: at most `limit` tiles hold a slot at once, FIFO after
 *  that. A slot is identified by the grant callback it was handed out to, so
 *  release is exact — releasing a token that is still queued cancels the queue
 *  entry instead of wrongly freeing someone else's slot, and releasing a token
 *  that holds no slot (released already, or never granted) does nothing: a
 *  counter there let a second release free a slot nobody gave back, and the cap
 *  went up by one each time. */
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
    release(grant: () => void) {
      const queued = waiting.indexOf(grant);
      if (queued >= 0) {
        waiting.splice(queued, 1); // still waiting — never held a slot
        return;
      }
      if (!holding.delete(grant)) return; // holds no slot — nothing to hand back
      const next = waiting.shift();
      if (next) {
        holding.add(next);
        next();
      }
    },
  };
}
