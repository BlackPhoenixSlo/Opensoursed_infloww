/** Creator statistics' layout save queue (useCreatorCols), dependency-free so UserContext can drop it on an identity
 *  switch without importing the hook. One PUT at a time, then the latest layout queued, each sent once. `revert`: the
 *  queuing mount's draft back to the Relay's layout when its save fails. `principal`: who queued it. */
export const creatorColsQueue: {
  inFlight: boolean;
  next: { cols: string[]; principal: string; revert: () => void } | null;
} = { inFlight: false, next: null };

/** An identity switch: the previous principal's queued layout is dropped (clearIdentityMemory). */
export function forgetCreatorColsQueue(): void {
  creatorColsQueue.next = null;
}
