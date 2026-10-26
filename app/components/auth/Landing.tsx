"use client";

/**
 * Landing: the /login page (bare, signed in or not: AuthGate). Sign in links
 * to Register with "Don't have an account? Sign up", Register links back
 * with "Already have an account?"; `?mode=register` opens Register and `?username=` prefills the
 * username and focuses the password (the public site's /signup/ and /login/
 * hand off here that way).
 *
 * On submit Sign in posts once to /auth/sign-in (lib/twoFactor.ts `signIn`),
 * which checks owners then employees and sets the matching session cookie;
 * Register calls UserContext.register(). Then it goes to `?next=` if present,
 * else the Dashboard: Messages Pro is a window of its own, opened from the
 * sidebar (ADR-0002), never the app's main page.
 *
 * Sign in wears the site's dark Inflowwww sign-in look (web/src/login.njk,
 * web/src/_includes/auth.njk: their app's login screen, our words); Register
 * wears the site's sign-up layout (web/src/signup.njk: their signup page,
 * with the required agree box) and goes back via "Already have an account?". Both via
 * `data-look="site"`, the scoped tokens in app/globals.css, so the hand-off
 * does not feel like leaving the site. Pink field lines follow the browser's
 * :user-invalid, and the submit button stays brown while the form is
 * :invalid (CSS only, the button is not disabled).
 */

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useUser } from "@/contexts/UserContext";
import { useInDesktopApp } from "@/hooks/useInDesktopApp";
import { SITE_URL } from "@/lib/site";
import { errorCode, signIn, TwoFactorRequired, type TwoFactorChallenge } from "@/lib/twoFactor";
import TwoFactorStep from "@/components/auth/TwoFactorStep";
import {
  Badges, Bang, EyeIcon, EyeOffIcon, HINT, INPUT, INPUT_LOGIN, Logo, Notice, PINK, PINK_TEXT, UNDERLINE, WRAP,
} from "@/components/auth/SiteLook";
import { BRAND_NAME } from "@/lib/brand";

type Mode = "login" | "register";

export default function Landing() {
  const { register, clearUserLocally } = useUser();
  const router = useRouter();
  const sp = useSearchParams();
  const inApp = useInDesktopApp();
  const nextHref = sp.get("next") || "/";

  const [mode, setMode] = useState<Mode>(sp.get("mode") === "register" ? "register" : "login");
  const prefilled = sp.get("username") ?? "";
  const [username, setUsername] = useState(prefilled);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);
  // The password was right and the account has 2FA on (or its Agency requires it): the code step.
  const [challenge, setChallenge] = useState<TwoFactorChallenge | null>(null);
  // The Relay's typed `account_deactivated` refusal (6.14): why, in a banner over the form.
  const [deactivated, setDeactivated] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setDeactivated(null);
    setBusy(true);
    try {
      const u = username.trim().toLowerCase();
      if (mode === "login") {
        await signIn(u, password);
        signedIn();
      } else {
        // Owner registration only. Chatter registration requires an
        // owner-issued invite token (security) and lives on
        // /chatter-login?token=… exclusively.
        await register(u, password);
        router.replace(nextHref);
      }
    } catch (err) {
      if (err instanceof TwoFactorRequired) setChallenge(err.challenge);
      else if (errorCode(err) === "account_deactivated") setDeactivated((err as Error).message);
      else setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  /** Signed in (the Relay set the cookie, an owner's or an employee's): drop the previous identity's
   *  caches and start the providers over with a hard navigation, so they mount as the new principal. */
  function signedIn() {
    clearUserLocally();
    window.location.replace(nextHref);
  }

  function anotherAccount() {
    setChallenge(null);
    setDeactivated(null);
    setUsername("");
    setPassword("");
  }


  const isRegister = mode === "register";
  const switchTo = (m: Mode) => { setMode(m); setError(null); };
  // Sign in follows their app's login screen (48px fields, 16px labels 8px above); Register their signup page.
  const label = isRegister ? "block text-xl font-medium" : "block text-base font-medium";
  const fieldGap = isRegister ? "mt-3" : "mt-2";
  const eye = isRegister ? "size-6" : "size-5";

  // `group`: the submit button reads the form's :invalid state (brown until every field is valid,
  // and on Register until the agree box is ticked, as on the site's /signup/).
  const form = challenge ? (
    <TwoFactorStep
      challenge={challenge}
      inputClass={INPUT_LOGIN}
      buttonClass={LOGIN_BUTTON}
      onSignedIn={signedIn}
      onCancel={anotherAccount}
    />
  ) : (
    <form onSubmit={onSubmit} className="group">
      {deactivated && (
        <div role="alert" className="mb-6 rounded-lg border border-[#fb609f]/50 bg-[#2a1219] p-4 text-base">
          <p className="font-medium text-[#fb609f]">Account deactivated</p>
          <p className="mt-1 text-white/85">{deactivated}</p>
          <button type="button" onClick={anotherAccount} className={`mt-3 ${LINK}`}>
            Sign in with another account
          </button>
        </div>
      )}
      <div className={isRegister ? "mt-8" : ""}>
        <label htmlFor="landing-username" className={label}>Username</label>
        <input
          id="landing-username"
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder={isRegister ? "name.agency" : "name.not-an-email"}
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
          minLength={3}
          maxLength={32}
          pattern="[a-zA-Z0-9_.\-]{3,32}"
          className={`peer ${isRegister ? INPUT : INPUT_LOGIN} ${fieldGap}`}
        />
        <p className={`hidden peer-user-invalid:flex ${PINK}`} aria-hidden="true">
          <Bang />
          Username is invalid. Enter a correct username, not an email
        </p>
        {isRegister && (
          <p className={`${HINT} peer-user-invalid:hidden`}>
            3 to 32 characters: a–z, 0–9, dot, underscore or hyphen. Capitals become lowercase.
          </p>
        )}
      </div>

      <div className="mt-6">
        <label htmlFor="landing-password" className={label}>Password</label>
        <div className={`relative ${fieldGap}`}>
          <input
            id="landing-password"
            type={showPw ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={isRegister ? "Create a password" : "Password"}
            autoComplete={isRegister ? "new-password" : "current-password"}
            required
            minLength={6}
            autoFocus={prefilled !== ""}
            className={isRegister ? `${INPUT} pr-20` : `${INPUT_LOGIN} pr-12`}
          />
          {/* Inside the field on sign-in, a separate square beside it on register (their two screens). */}
          <button
            type="button"
            onClick={() => setShowPw((v) => !v)}
            aria-pressed={showPw}
            aria-controls="landing-password"
            className={`absolute inset-y-0 right-0 flex items-center justify-center text-white/85 hover:text-white focus-visible:outline-2 focus-visible:outline-accent ${isRegister ? "w-16 rounded-r-xl bg-[#272727] hover:bg-[#303030]" : "w-12 rounded-r-lg"}`}
          >
            {showPw ? <EyeIcon className={eye} /> : <EyeOffIcon className={eye} />}
            <span className="sr-only">Show password</span>
          </button>
        </div>
        {isRegister && <p className={HINT}>Must be at least 6 characters</p>}
      </div>

      {isRegister ? (
        <>
          <div className="mt-6 flex items-start gap-3">
            {/* Checked in the browser only (required, so the form stays :invalid until ticked); never sent.
                Their outlined 18px box, orange with a white tick once ticked. */}
            <span className="relative mt-1.5 flex size-[18px] shrink-0">
              <input
                id="landing-agree"
                type="checkbox"
                required
                className="peer size-[18px] appearance-none rounded-[3px] border-2 border-[#313131] bg-transparent checked:border-accent checked:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              />
              <svg className="pointer-events-none absolute inset-0 hidden size-[18px] text-white peer-checked:block" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
                <path d="m4.5 9.5 3 3 6-7" />
              </svg>
            </span>
            <label htmlFor="landing-agree" className="text-lg text-white/85">
              I agree to the{" "}
              <a className={UNDERLINE} href={`${SITE_URL}/legal/privacy/`}>Privacy Policy</a> and{" "}
              <a className={UNDERLINE} href={`${SITE_URL}/legal/terms/`}>Terms of Service</a>
            </label>
          </div>
          {/* Their Cloudflare Turnstile box. */}
          <p className="mt-8 text-base text-white/70">
            <span className="line-through" title="No CAPTCHA on this page.">Let us know you&apos;re human</span>
            <span className="sr-only"> (No CAPTCHA on this page.)</span>{" "}
            <span aria-hidden="true">We&apos;ll take your word for it.</span>
          </p>
        </>
      ) : (
        <div className="my-6 flex flex-wrap items-center justify-between gap-x-4 gap-y-3 text-base">
          {/* Their "Remember me" box. The app always remembers you (service/auth.py: a session lasts until 30 days
              without use), so this is a picture of a ticked box, not a form control (as web/src/login.njk). */}
          <p className="flex items-center gap-3">
            <span aria-hidden="true" className="flex size-4 shrink-0 items-center justify-center rounded-[4px] bg-accent text-white">
              <svg className="size-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" focusable="false">
                <path d="m3.5 8.5 3 3 6-7" />
              </svg>
            </span>
            <span>Remember me <span className="text-sm text-white/[0.62]">(always)</span></span>
          </p>
          {/* Their "Forgot password?" link. The app has no reset flow (service/auth.py keeps no email). */}
          <details className="relative">
            <summary className={`${LINK} cursor-pointer list-none [&::-webkit-details-marker]:hidden`}>Forgot password?</summary>
            <p className="absolute right-0 z-10 mt-2 w-64 rounded-xl bg-[#1f1f1f] p-4 text-sm text-white/85 shadow-lg ring-1 ring-white/10">
              There is no reset link. The app keeps no email address to send one to.
            </p>
          </details>
        </div>
      )}

      {error && (
        <p role="alert" className={`flex ${PINK_TEXT} ${isRegister ? "mt-6" : "mb-6"}`}>
          <Bang />
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy}
        className={`flex w-full items-center justify-center bg-accent font-medium text-[#0c0c0c] hover:bg-[#ff8d65] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60 motion-safe:transition-colors ${
          isRegister
            ? "mt-6 h-[58px] rounded-xl text-lg group-invalid:bg-[#4b2d22] group-invalid:text-[#4b4b4b]"
            : "h-12 rounded-lg text-base group-invalid:bg-[#45291e] group-invalid:text-[#1b100b]"
        }`}
      >
        {busy ? "…" : isRegister ? "Create account" : "Login"}
      </button>

      {!isRegister && (
        <p className="mt-4 text-sm text-pretty text-white/[0.62]">
          By using {BRAND_NAME}, you agree to our{" "}
          <a className={LINK} href={`${SITE_URL}/legal/privacy/`}>
            Privacy Policy
          </a>{" "}
          and{" "}
          <a className={LINK} href={`${SITE_URL}/legal/terms/`}>
            Terms of Service
          </a>
        </p>
      )}
    </form>
  );

  // The desktop app, on both layouts: a plain <a> (/download is a static file outside the router), left out inside
  // the app. The server renders as if in the app, so it appears after hydration on the web and never flashes there.
  const download = !inApp && (
    <p className="mt-2 text-sm text-pretty text-white/[0.62]">
      <a className={LINK} href="/download">Download the desktop app</a> for Mac and Windows.
    </p>
  );

  // Register wears the site's /signup/ layout (web/src/signup.njk): logo on top, form left, pitch right.
  if (isRegister) {
    return (
      <main data-look="site" className="flex min-h-dvh flex-col bg-[#121212] text-fg">
        <div className={`${WRAP} pt-5`}>
          <Logo />
        </div>
        <div className={`${WRAP} grid flex-1 gap-14 pt-10 pb-16 sm:pt-14 md:grid-cols-2 md:gap-16 lg:gap-24 lg:pt-20 lg:pb-24`}>
          <section aria-labelledby="landing-title" className="w-full max-w-lg">
            <h1 id="landing-title" className="text-4xl font-medium tracking-tight sm:text-[43px]">Sign up</h1>
            {form}
            <p className="mt-8 text-base text-white/85">
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => switchTo("login")}
                className={LINK}
              >
                Sign in
              </button>
            </p>
            <p className="mt-2 text-sm text-pretty text-fg-dim">
              Chatters don&apos;t register here. They join through an invite link from their agency&apos;s owner.
            </p>
            {download}
          </section>

          <section aria-labelledby="landing-pitch" className="md:pt-6">
            <h2 id="landing-pitch" className="text-[clamp(2.25rem,4vw,3.75rem)] leading-[1.08] font-semibold tracking-tight text-balance">
              Accelerate your agency&apos;s success. Not ours.
            </h2>
            <p className="mt-6 max-w-xl text-xl text-pretty text-white/90">
              Sign up and access every built feature for 7 days, then the 7 after that, and so on—no credit card
              needed, because there is no card form. Get started in just two fields.
            </p>
            <p className="mt-4 max-w-xl text-base text-pretty text-fg-dim">
              One {BRAND_NAME} app serves many agencies. Each owner signs up with their own username, employees get their
              own logins through their owner&apos;s invite, and each agency account sees only its own creators and their
              chats (the one exception is in the{" "}
              <a className={UNDERLINE} href={`${SITE_URL}/legal/privacy/`}>Privacy Policy</a>).
            </p>
            <Badges />
          </section>
        </div>
        <Notice />
      </main>
    );
  }

  return (
    <main data-look="site" className="flex min-h-dvh flex-col bg-bg text-fg">
      {/* Their columns: text from x 313, the 355px form from x 715 (757 wide in all, 77 between). */}
      <div className="mx-auto grid w-full max-w-[821px] flex-1 content-center gap-12 px-5 py-14 sm:px-8 md:grid-cols-[1fr_355px] md:gap-[77px] lg:py-24">
        <section aria-labelledby="landing-title" className="max-md:contents md:flex md:flex-col">
          <div>
            <Logo mark="size-8" />
            <h1 id="landing-title" className="mt-6 text-[28px] leading-tight font-normal tracking-tight">Welcome to {BRAND_NAME}</h1>
          </div>
          {/* On a phone the news and version go below the form (max-md:contents lets order-last reach the grid). */}
          <div className="max-md:order-last md:mt-auto md:pt-16">
            <p className="text-base text-pretty">
              To stay up-to-date on our latest releases and other updates, check out{" "}
              <a className={LINK} href={`${SITE_URL}/changelog/`}>
                {BRAND_NAME} News
              </a>
              , which is a git log.
            </p>
            <p className="mt-4 text-sm text-white/[0.62]">Version 0.0.0.wwww</p>
          </div>
        </section>

        <section aria-label="Sign in" className="w-full">
          {form}
          <p className="mt-8 text-base text-white/85">
            Don&apos;t have an account?{" "}
            <button type="button" onClick={() => switchTo("register")} className={LINK}>
              Sign up
            </button>
          </p>
          <p className="mt-2 text-sm text-pretty text-white/[0.62]">
            Chatters sign in here too, with the username they picked when they opened their owner&apos;s invite.
          </p>
          {download}
        </section>
      </div>
      <Notice />
    </main>
  );
}

const LOGIN_BUTTON = "flex h-12 w-full items-center justify-center rounded-lg bg-accent text-base font-medium text-[#0c0c0c] hover:bg-[#ff8d65] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60";
const LINK = "font-medium text-accent hover:underline hover:underline-offset-4 focus-visible:outline-2 focus-visible:outline-accent";
