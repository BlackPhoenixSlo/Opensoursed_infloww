/**
 * The dark Inflowwww "site look" pieces shared by the signed-out auth screens
 * (Landing.tsx at /login, app/chatter-login/page.tsx for invited employees).
 * Render them inside a `data-look="site"` root: the scoped tokens in
 * app/globals.css make `bg`, `fg`, `fg-dim` and `accent` the site's colours.
 */

import { SITE_URL } from "@/lib/site";

/** Our "OIF" square, redrawn (not Infloww's asset): their white IF mark with an O in front, plus an orange dot. */
export function IfMark({ className = "size-10" }: { className?: string }) {
  return (
    <svg className={`${className} shrink-0`} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <rect width="40" height="40" rx="9" fill="#fff" />
      <rect x="6" y="12" width="7" height="16" rx="3.5" fill="none" stroke="#0c0c0c" strokeWidth={4} />
      <rect x="18" y="10" width="4" height="20" fill="#0c0c0c" />
      <rect x="25" y="10" width="4" height="20" fill="#0c0c0c" />
      <rect x="25" y="10" width="11" height="4" fill="#0c0c0c" />
      <rect x="25" y="18" width="8" height="4" fill="#0c0c0c" />
      <circle cx="33" cy="28" r="2.5" fill="#f88056" />
    </svg>
  );
}

/** The mark and the INFLOWWWW wordmark, linking home. `mark` sizes the square (their login screen's is 32px). */
export function Logo({ mark = "size-10" }: { mark?: string }) {
  return (
    <a
      href={SITE_URL}
      aria-label="Inflowwww home"
      className="inline-flex min-h-11 items-center gap-3 focus-visible:outline-2 focus-visible:outline-accent"
    >
      <IfMark className={mark} />
      <span className="text-[1.65rem] leading-none font-extrabold tracking-tight uppercase">
        Infloww<span className="text-white/70">w</span><span className="text-white/55">w</span>
      </span>
    </a>
  );
}

export function Notice() {
  return (
    <p className="px-5 pb-6 text-center text-xs text-fg-dim">
      Unofficial parody of infloww.com. Not affiliated with Infloww. The software is real; the jokes are ours.{" "}
      <a
        href={SITE_URL}
        className="underline underline-offset-4 hover:text-fg focus-visible:outline-2 focus-visible:outline-accent"
      >
        Back to the site
      </a>
    </p>
  );
}

/** The site's two parody badges (web/src/_includes/auth.njk badges()). */
export function Badges() {
  return (
    <ul aria-label="Badges" className="mt-12 flex flex-wrap items-center gap-x-12 gap-y-8 text-white/60">
      <li className="flex items-center gap-3">
        <Laurel className="h-14 w-6 shrink-0" />
        <span className="text-center">
          <span className="block text-sm tracking-[0.3em]" aria-hidden="true">☆☆☆☆☆</span>
          <span className="block text-xs">Community Choice (Since never)</span>
          <strong className="block text-base leading-tight font-semibold">
            Voted #1 by nobody.<br />We weren&apos;t in the poll.
          </strong>
        </span>
        <Laurel className="h-14 w-6 shrink-0 -scale-x-100" />
      </li>
      <li className="flex items-center gap-3">
        <svg className="size-14 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
          <path d="M12 2.5 4 5.5v6c0 5 3.4 8.7 8 10 4.6-1.3 8-5 8-10v-6Z" />
          <path d="m8.5 12 2.5 2.5 4.5-5" />
        </svg>
        <span>
          <span className="block text-xs">Trusted by</span>
          <a className="block text-base font-semibold text-white/75 hover:text-white" href={`${SITE_URL}/case-studies/`}>
            5 agencies, all fictional
          </a>
          <span className="mt-1 flex items-center" aria-hidden="true">
            {["ET", "FC", "LI", "PP", "SS"].map((initials) => (
              <span
                key={initials}
                className="-ml-1.5 flex size-6 items-center justify-center rounded-full bg-neutral-700 text-[0.55rem] font-bold text-white/80 ring-2 ring-[#121212] first:ml-0"
              >
                {initials}
              </span>
            ))}
            <svg className="ml-2 size-5 text-accent" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true" focusable="false">
              <path d="M7 17 17 7M8 7h9v9" />
            </svg>
          </span>
        </span>
      </li>
    </ul>
  );
}

function Laurel({ className }: { className: string }) {
  return (
    <svg className={className} viewBox="0 0 24 56" fill="currentColor" aria-hidden="true" focusable="false">
      <path d="M20 54C9 48 4 36 6 22 7 15 10 8 15 3l1.5 1C12 9 9 15 8.2 22 6.6 35 11 46 21 52Z" />
      <ellipse cx="4.5" cy="40" rx="2.4" ry="5" transform="rotate(-35 4.5 40)" />
      <ellipse cx="3.6" cy="30" rx="2.2" ry="4.6" transform="rotate(-15 3.6 30)" />
      <ellipse cx="4.6" cy="20" rx="2.1" ry="4.4" transform="rotate(10 4.6 20)" />
      <ellipse cx="8" cy="11" rx="2" ry="4.2" transform="rotate(30 8 11)" />
      <ellipse cx="12.5" cy="47" rx="2.4" ry="4.8" transform="rotate(-70 12.5 47)" />
    </svg>
  );
}

/** The sign-up field (their signup.infloww.com: 58px, #111111, a hair darker than the #121212 page). */
export const INPUT =
  "block h-[58px] w-full rounded-xl border border-transparent bg-[#111111] px-5 text-lg text-fg placeholder:text-white/50 focus-visible:border-accent focus-visible:outline-none user-invalid:bg-[#23141a]";
/** The sign-in field (their app's login screen: 48px, radius 8, #161616 on the #0c0c0c page, 16px text). */
export const INPUT_LOGIN =
  "block h-12 w-full rounded-lg border border-transparent bg-[#161616] px-4 text-base text-fg placeholder:text-white/50 focus-visible:border-accent focus-visible:outline-none user-invalid:bg-[#23141a]";
/** Their pink field message: 16px #fb609f, a 20px circle-bang, 8px under the field (PINK carries the 8px). */
export const PINK_TEXT = "items-start gap-2 text-base text-[#fb609f]";
export const PINK = `mt-2 ${PINK_TEXT}`;
export const HINT = "mt-3 text-sm text-[#a4a4a4]";
export const UNDERLINE = "text-white underline decoration-white/40 underline-offset-[6px] hover:decoration-white";
export const WRAP = "mx-auto w-full max-w-6xl px-5 sm:px-8";

export function Bang() {
  return (
    <svg className="mt-0.5 size-5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 7v6M12 16.5v.5" />
    </svg>
  );
}

export function EyeIcon({ className = "size-6" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M2.2 12C3.4 8.6 7 5 12 5s8.6 3.6 9.8 7c-1.2 3.4-4.8 7-9.8 7s-8.6-3.6-9.8-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

export function EyeOffIcon({ className = "size-6" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M10.6 5.1A10 10 0 0 1 12 5c5 0 8.6 3.6 9.8 7a11 11 0 0 1-2.4 3.6M6.6 6.6A11 11 0 0 0 2.2 12c1.2 3.4 4.8 7 9.8 7a10 10 0 0 0 5.4-1.6" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
      <path d="m3 3 18 18" />
    </svg>
  );
}
