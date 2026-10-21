# Next session: fix the parody sign-in and sign-up pages (real password, multi-agency truth)

Paste this whole file as the first message of the next session.

---

Fix the parody `/signup/` and `/login/` pages on the `web/` site. They shipped on 2026-10-12 (merge
9fc6bdba on main) and the user rejected them on sight. Read this whole brief first.

Repo: <repo>, branch main. Work in a worktree branch, merge to main
with `--no-ff` when the checks pass. Spawn Opus agents (high effort) for the work; keep your own context
small. Every agent brief must say "do not spawn sub-agents". Follow YAGNI. Nothing is pushed.

## What the user said

> wtf is this psw on the page its multi agency system everyone needs to login and models do not share
> that was already how it was always

Two complaints:

1. **The password "field" is a fake.** Where the password field belongs, both pages show a dashed box
   saying "You type it on the app itself, on your server. It never passes through this page." The user
   wants a real login: username AND password on the page, and submitting logs you in.
2. **The copy gets the product wrong.** Inflowwww is a multi-agency system. One running instance
   serves many agencies. Every owner and every chatter has their own login. Models (creators) are not
   shared between agencies. That has always been how it works. The pages instead talk as if the reader
   is the only user of a server they run themselves.

## What shipped (the starting point)

- `web/src/signup.njk`, `web/src/login.njk`, shared parts in `web/src/_includes/auth.njk`. Plain GET form,
  username field only, hands off to `{{ site.appUrl }}/login?mode=register&username=…` or
  `/login?username=…`. The dashed box is in `auth.njk` (around line 28).
- Wrong framing lines (grep for `own server`, `your server`, `this server`):
  - `web/src/signup.njk:41` "Your agency, on your own server."
  - `web/src/signup.njk:43` "…for as long as your server runs…"
  - `web/src/login.njk:18` "Ask whoever runs your server."
  - `web/src/login.njk:34-37` "Welcome back to your own server." / "Sessions and the database live on your server…"
  - `web/src/_includes/auth.njk:28` the dashed password box
  - `app/components/auth/Landing.tsx:109` "Sessions and the database live on this server."
  Check the landing, privacy and terms pages for the same framing that came in with that merge.
- The app's `/login` (`app/components/auth/Landing.tsx`) was restyled to the site's light look, reads
  `?username=` and focuses the password. `SITE_URL` constant, `[data-look="site"]` rule in
  `app/app/globals.css`. Keep that.
- Review reports from the first round: `/tmp/parody-review/{devils-advocate,six-hats,reviewer}.md`
  (may be gone after a reboot). Headless script: `/tmp/parody-review/run.mjs`.

## Facts about auth (verified 2026-10-13)

- Relay endpoints `POST /auth/register` and `POST /auth/login` in `service/auth.py` (around lines 508 and
  530) take a JSON body only (`Body(...)` pydantic models). A urlencoded HTML form post gets a 422.
- They set the `chatterly_session` cookie with `samesite="lax"` and return JSON, no redirect.
- The Next app proxies `/auth/:path*` to the relay (`app/next.config.ts` around line 119). `/auth/*` is
  exempt from the share-token gate on both sides.
- No CORS anywhere in app/ or service/. The static site and the app are different origins
  (`site.url` is GitHub Pages; `site.appUrl` is `http://localhost:3001`).
- Chatters sign up only through an owner invite at `/chatter-login?token=…`; they can sign in at
  `/chatter-login`, and `/login` also falls back to chatter login.
- Owner username: 3-32 chars, `[a-zA-Z0-9_.-]`, lowercased; reserved admin, root, system, chatterly,
  founder (`service/auth.py:71`). Password 6+. No email, no reset flow.
- Before writing any copy about "models are not shared", confirm it in code (how creators/OF accounts
  are scoped to an owner) and in README.md / docs/routes.md. The voice guide only allows Inflowwww
  claims that README.md or docs/routes.md back; add a line to docs/routes.md if needed.

## Deliverable

1. **The flow the user wants (fixed, do not change it):** the landing page's **Log in** and **Register**
   buttons (header, hero, mobile menu) keep opening the site's own `/login/` and `/signup/` pages. Those
   pages are the login: the visitor types username AND password there and submits. On success they go
   straight into the app, already signed in, on the same page the app's own login lands on today
   (`/messages-pro`). They never see the app's `/login` form in between. On failure they stay on the
   site page with the error shown.
   Both pages get a username field and a real password field (`type="password"`,
   `autocomplete="current-password"` on login, `"new-password"` on signup, show/hide toggle like theirs,
   "Must be at least 6 characters" under it). No dashed box, no "type it on the app".
   **How, without CORS:** a top-level HTML form POST needs no CORS. Add one small Next route handler on
   the app (for example `app/app/auth/form/route.ts`) that accepts the urlencoded form, calls the relay's
   JSON `/auth/login` or `/auth/register`, copies the `Set-Cookie`, and 303-redirects to the app
   dashboard on success or back to the site page with `?error=` on failure. The static pages read
   `?error=` and show it. Map the relay's errors (409 taken, 401 wrong password, 400 reserved/invalid)
   to plain messages. Keep the password out of every URL and log. Check that the `samesite=lax` cookie
   set on the 303 response is kept by the browser and sent on the redirect (it should be, since it is a
   top-level navigation; prove it in the headless check). Say why in the commit.
   Do not add CORS. Do not change how the relay stores or checks passwords.
2. **Copy that tells the truth.** One instance, many agencies. Each agency owner signs up with their own
   username. Chatters get their own logins through the owner's invite. Each agency's creators/models and
   chats stay with that agency (only if step "Facts" confirms it). Drop every "your own server" line
   listed above. Keep the parody shape (looks like theirs, says the opposite) and the voice guide
   (`docs/parody-voice.md`, one joke per section). Badges stay fictional and labelled.
3. **Dark render.** The user's screenshot of `/signup/` rendered dark, but `web/src/main.css` sets
   `color-scheme: light`. Find out why before changing anything (browser auto-dark, an extension, or a
   real CSS path). Fix it only if it is the site's fault.
4. App `/login` keeps working on its own (direct visits, `?mode=register`, `?username=`), with no
   "Who's chatting?" box for a signed-out visitor. Fix its one-liner copy to match (2).

## Checks (all must pass before merging; report the exact last line of each)

- `pnpm -C web build`; Lighthouse 100 on all four categories for `/signup/` and `/login/` (or whatever
  replaces them), desktop and mobile, the way `web/README.md` records.
- `cd app && pnpm lint` (0 errors) `&& pnpm typecheck && pnpm test:run`; `Landing.test.tsx` and
  `AuthGate.test.tsx` keep passing; tests for any new route handler (success, wrong password, taken
  username, reserved name, password never echoed).
- Headless end to end against a real relay: landing → Register → fill username + password → submit →
  signed in inside the app (dashboard, not the form). Landing → Log in → same with that account → signed
  in. Wrong password → back on the page with the error shown. Screenshot at 1280 and 390.
  Ports 3001 and 4173 may be the user's own dev servers; run yours on other ports and leave theirs alone.
- Reviews before merging, read-only agents, reports under `/tmp/parody-review-2/`: devils-advocate and
  six-hats on the copy and the design choice, reviewer on the diff. Read-only agents cannot write files;
  save their reports yourself.

## Rules

- No real company badges, award names or "4,000+ agencies"-style numbers.
- Commit messages end with the attribution line the session gives you.
- Report at the end: design chosen and why, files changed, the exact last line of every check,
  screenshot paths, anything skipped.
