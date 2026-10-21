# Next session: parody sign-in and sign-up pages, in step with the landing page

Paste this whole file as the first message of the next session.

---

Build the parody sign-up and sign-in pages for the `web/` site and wire the landing page to them, so
clicking **Log in** or **Register** on the landing page opens a page that looks like it belongs to the
same site, and that page hands off to the real app.

Repo: <repo>, branch main. Work in a worktree branch, merge to main
when the checks pass. Spawn Opus agents for the writing and the build; keep your own context small.
Follow YAGNI.

## What exists today (do not redo)

- `web/` is an Eleventy 3 + Nunjucks + Tailwind v4 parody of infloww.com, light Framer-style theme
  (cream `#f1ede5`, ink, black pill buttons, forest-green accent). Build: `pnpm -C web build`;
  preview: `pnpm -C web preview` (port 4173). Sources of truth for every word on the site:
  `docs/parody-voice.md`, `docs/infloww-site-inventory.{md,json}`, `docs/infloww-landing-snapshot.md`,
  `README.md`, `docs/routes.md`. A claim not in them does not go on the site.
- Landing header and hero already have **Log in** and **Register** buttons (commit f56e34c0). They
  point at `{{ site.appUrl }}/login` and `{{ site.appUrl }}/login?mode=register`; `appUrl` is in
  `web/src/_data/site.json` (currently `http://localhost:3001`).
- The app's `/login` (Next, `app/components/auth/Landing.tsx`) is a dark page with a Sign in / Register
  toggle; `?mode=register` opens the Register tab (commit 22de59e9 also fixed the "Who's chatting?"
  picker that used to cover it for signed-out visitors). Owner registration is open, no email, username
  + password only (3–32 chars, lowercase a–z 0–9 . _ -; password 6+). Chatters register only through an
  owner invite link at `/chatter-login?token=…`.
- Today the hand-off is ugly: a light cream landing page jumps to a dark app page that looks like a
  different product. That is the problem to solve.

## Reference: their sign-up page

`docs/infloww-signup-snapshot-2026-10-12.png` is their sign-up page as of 2026-10-12: dark page, logo top
left, language picker top right, left column "Sign up" form (Email address, Password with show/hide,
"Must be at least 8 characters", "I agree to the Privacy Policy and Terms of Condition" checkbox,
Cloudflare Turnstile "Let us know you're human", orange "Sign up with email" button), right column
headline "Accelerate your agency's success." with "Sign up and access all features for 7 days—no credit
card needed. Get started in just two minutes." and two badges ("Community Choice (Since 2022) #1 OnlyFans
Management Tool", "Trusted by 4,000+ agencies"). Look at their sign-in page too (same layout, assume
Email + Password + "Forgot password?" + "Sign in" + "Don't have an account? Sign up") and record what
you see in `docs/infloww-landing-snapshot.md` with the date.

## Deliverable

1. `web/src/signup.njk` → `/signup/` and `web/src/login.njk` → `/login/`, parody versions of their two
   pages, in OUR light theme (the joke stays "looks exactly like theirs, says the opposite"): same
   two-column layout, same field order, our copy. Right column says what is true: no trial because there
   is nothing to pay for, no email because the app does not collect one, badges become our honest ones
   ("Trusted by 5 agencies, all fictional" etc., reuse what the landing page already says). Checkbox
   text points at our real `/legal/terms/` and `/legal/privacy/`. No Turnstile; a struck-through
   "Let us know you're human" line with the usual tooltip joke is fine. Every word passes the voice
   guide and the inventory.
2. The form on those pages is real, not a mock: username + password fields that match the app's rules,
   and submit goes to the app. Two acceptable designs, pick one and say why in the commit:
   a. The static page is a front door only: its button is a link to `{{ site.appUrl }}/login?mode=register`
      (or `/login`), and the APP page is restyled to match the parody site (light theme, same header,
      same fonts) when reached from it. Simplest and honest.
   b. The static page posts to the app's register/login endpoint cross-origin. Only if the relay already
      allows it; do not add CORS or open anything new for this.
3. Landing page header + hero: Log in → `/login/`, Register → `/signup/` (site-internal now), mobile menu
   too. Keep "Deploy it yourself" as the primary button.
4. The app side of the hand-off is tidy: `/login` and `/login?mode=register` render the bare form for a
   signed-out visitor (already true), and the form's look matches the parody pages closely enough that the
   click does not feel like leaving the site. At minimum: same page background tone, same heading
   font-stack, a "Back to the site" link to `{{ site.url }}`.
5. Tests and checks, all must pass before merging: `pnpm -C web build`; the site's existing checks
   (Lighthouse 100s were the bar; keep it); `cd app && pnpm lint` (0 errors) `&& pnpm typecheck &&
   pnpm test:run`; the `Landing.test.tsx` and `AuthGate.test.tsx` cases keep passing; a Playwright or
   headless check that: landing → Register → the register form is on screen with no "Who's chatting?"
   box, and landing → Log in → the sign-in form. Screenshot both at 1280 and 390 wide and put the paths
   in the report.
6. Reviews before merging, read-only agents: devils-advocate and six-hats on the pages' copy and on the
   design choice in (2); a reviewer pass on the diff. Save their reports under `/tmp/parody-review/`.

## Rules

- No real company badges, award names or "4,000+ agencies"-style numbers on our pages; fictional and
  labelled, like the rest of the site.
- Nothing is pushed. Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Report at the end: what design in (2) was chosen and why, the routes added, the exact last line of every
  check, the screenshot paths, anything skipped.
