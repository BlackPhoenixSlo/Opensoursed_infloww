/**
 * The 7-day free trial, counted from the signed-in principal's own
 * registration (`created_at` on /auth/me or /chatter/me). Display only:
 * nothing is gated on it.
 */

export const TRIAL_DAYS = 7;
export const BUY_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";

const DAY_MS = 24 * 60 * 60 * 1000;

/** Days left as Infloww's header counts them (whole days remaining + 1, so
 *  "7 days left" right after registering and "1 day left" on the last day),
 *  0 once the trial is over, or null with no registration time. */
export function trialDaysLeft(createdAt: string | null | undefined, now: number = Date.now()): number | null {
  if (!createdAt) return null;
  const start = Date.parse(createdAt);
  if (Number.isNaN(start)) return null;
  const remaining = start + TRIAL_DAYS * DAY_MS - now;
  return remaining > 0 ? Math.floor(remaining / DAY_MS) + 1 : 0;
}
