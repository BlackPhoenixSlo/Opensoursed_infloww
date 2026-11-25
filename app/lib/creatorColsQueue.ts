export const creatorColsQueue: {
  inFlight: boolean;
  next: { cols: string[]; principal: string; revert: () => void } | null;
} = { inFlight: false, next: null };

export function forgetCreatorColsQueue(): void {
  creatorColsQueue.next = null;
}
