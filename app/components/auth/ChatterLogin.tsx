"use client";

/**
 * ChatterLogin: the /chatter-login page, the sign-in surface for the second
 * principal. AuthGate renders it bare (no app shell or "who's chatting"
 * picker around it), the way /login renders <Landing>.
 *
 * Two modes:
 *   • With `?token=...` (invite link from an owner) → register form.
 *     If a User is currently signed in on this browser we explicitly
 *     log them out FIRST, so the new chatter cookie isn't shadowed by
 *     the owner cookie (AuthGate gives User precedence — would leave
 *     the chatter "registered but invisible" otherwise).
 *   • Without a token → login form for returning chatters.
 *
 * On success router.replace("/") so the app shell mounts under the
 * fresh chatter principal.
 *
 * Wears the dark Inflowwww site look (`data-look="site"`, shared pieces in
 * components/auth/SiteLook.tsx): their employee-invite screen as we imagine
 * it, invite card + form left, a parody pitch and fake shift card right.
 *
 * Path is intentionally NOT /chatter — that would shadow the relay
 * rewrite (memory: feedback_next_page_relay_collision).
 */

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { useChatter } from "@/contexts/ChatterContext";
import { useUser } from "@/contexts/UserContext";
import { useInDesktopApp } from "@/hooks/useInDesktopApp";
import { TwoFactorRequired, type TwoFactorChallenge } from "@/lib/twoFactor";
import TwoFactorStep from "@/components/auth/TwoFactorStep";
import { Bang, EyeIcon, EyeOffIcon, HINT, INPUT, Logo, Notice, PINK, WRAP } from "@/components/auth/SiteLook";
import { BRAND_NAME } from "@/lib/brand";

interface InvitePreview {
  username: string;        // owner who issued the invite
  expires_at: string;
  used: boolean;
}

export default function ChatterLogin() {
  const router = useRouter();
  const sp = useSearchParams();
  const token = sp.get("token") || "";
  const { chatter, login, register } = useChatter();
  const { user, clearUserLocally } = useUser();

  const isRegister = !!token;
  const inApp = useInDesktopApp();

  // Peek at the invite (read-only — doesn't consume) so the user knows
  // which owner is inviting them and that the link is still valid.
  const invitePreview = useQuery<InvitePreview | null>({
    queryKey: ["chatter", "invite-preview", token],
    queryFn: async () => {
      if (!token) return null;
      const r = await fetch(`/chatter/invite/${encodeURIComponent(token)}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!r.ok) return null;
      return (await r.json()) as InvitePreview;
    },
    enabled: !!token,
    staleTime: 60_000,
  });

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);
  const [challenge, setChallenge] = useState<TwoFactorChallenge | null>(null);

  // Already signed in as a chatter? Bounce straight to the app.
  // Owner signed in (with no token in URL) → also bounce: they probably
  // just clicked an old bookmark and there's nothing to do here.
  useEffect(() => {
    if (chatter) router.replace("/");
    else if (user && !token) router.replace("/");
  }, [chatter, user, token, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      const u = username.trim().toLowerCase();
      if (isRegister) {
        // Owner signed in on the same browser? Drop the User cookie
        // first so AuthGate doesn't keep showing the owner's view after
        // the chatter is created. Local-only clear — the chatter
        // register call sets the chatter cookie a moment later.
        if (user) clearUserLocally();
        await register(u, password, token, displayName.trim() || undefined);
      } else {
        await login(u, password);
      }
      // Hard navigation, not router.replace: the chatter cookie was
      // just set on the response and React Query has the new principal
      // seeded. A full page load guarantees the new cookie ships on
      // every subsequent fetch and re-mounts every provider from
      // scratch — what the user used to have to do manually with
      // "click refresh." A client-side transition was racing the
      // observer notifications and occasionally landed on AuthGate
      // while it still saw chatter=null.
      window.location.replace("/");
    } catch (err) {
      // 2FA on, or the Agency requires it (an invite sign-up sets it up here): the code step.
      if (err instanceof TwoFactorRequired) setChallenge(err.challenge);
      else setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
    // Note: no finally clearing busy — on success we hard-navigate so
    // the form unmounts before the next event loop tick anyway.
  }

  const invite = invitePreview.data;
  const owner = invite?.username;
  const inviteDead = invite?.used === true;
  const headline = !isRegister
    ? "Back for another shift?"
    : inviteDead
      ? "This invite has clocked out."
      : owner
        ? `@${owner} wants you on the team.`
        : "You've been invited to the team.";

  return (
    <main data-look="site" className="flex min-h-dvh flex-col bg-[#121212] text-fg">
      <div className={`${WRAP} pt-5`}>
        <Logo />
      </div>
      <div className={`${WRAP} grid flex-1 gap-14 pt-10 pb-16 sm:pt-14 md:grid-cols-2 md:gap-16 lg:gap-24 lg:pt-20 lg:pb-24`}>
        <section aria-labelledby="chatter-title" className="w-full max-w-lg">
          <p className="text-base font-medium text-accent">{isRegister ? "Employee invite" : "Employee sign-in"}</p>
          <h1 id="chatter-title" className="mt-3 text-4xl font-medium tracking-tight text-balance sm:text-5xl">{headline}</h1>
          {!isRegister && (
            <p className="mt-4 text-lg text-pretty text-white/80">
              Sign in with the username you picked when you opened your owner&apos;s invite.
            </p>
          )}

          {/* Invite context: who invited you, and is the link still good. */}
          {isRegister && invite && (
            inviteDead ? (
              <div className={DEAD_CARD}>
                <p className="flex items-start gap-2.5 font-medium text-[#ff5c9a]">
                  <Bang />
                  This invite link is no longer valid.
                </p>
                <p className="mt-2 text-base text-white/70">
                  It was used or it expired. Ask <span className="text-white">@{invite.username}</span> for a
                  fresh link; nobody here can extend it, including us.
                </p>
              </div>
            ) : (
              <div className="mt-8 flex items-center gap-4 rounded-2xl bg-white/[0.06] p-5">
                <span
                  aria-hidden="true"
                  className="flex size-14 shrink-0 items-center justify-center rounded-full bg-accent text-2xl font-bold text-[#0c0c0c] uppercase"
                >
                  {invite.username.charAt(0)}
                </span>
                <div className="min-w-0 text-base">
                  <p className="text-lg">
                    Invited by <span className="font-medium">@{invite.username}</span>
                  </p>
                  <p className="mt-1 text-white/70">
                    Role: <span className="rounded-md bg-white/10 px-2 py-0.5 text-sm font-medium text-white">Employee</span>
                  </p>
                  <p className="mt-1 text-sm text-fg-dim">
                    Link expires {new Date(invite.expires_at).toLocaleString()}. One use, no extensions.
                  </p>
                </div>
              </div>
            )
          )}
          {isRegister && invitePreview.isError && (
            <div className={DEAD_CARD}>
              <p className="flex items-start gap-2.5 font-medium text-[#ff5c9a]">
                <Bang />
                Invite token not found.
              </p>
              <p className="mt-2 text-base text-white/70">
                Double-check the URL or ask the owner for a fresh invite link. We looked under the couch too.
              </p>
            </div>
          )}

          {/* Owner cookie warning: heading into the register submit will
           *  sign them out of their owner account on this browser. */}
          {isRegister && user && (
            <p className="mt-6 rounded-2xl bg-white/[0.06] p-5 text-base text-white/70">
              You&apos;re currently signed in as <span className="text-white">@{user.username}</span>.
              Creating an employee account will sign you out and switch this
              browser to the new employee session.
            </p>
          )}

          {/* `group`: the submit button stays brown while the form is :invalid (as on /login). */}
          {challenge ? (
            <div className="mt-8">
              <TwoFactorStep
                challenge={challenge}
                inputClass={INPUT}
                buttonClass="flex h-14 w-full items-center justify-center rounded-xl bg-accent text-lg font-medium text-[#0c0c0c] hover:bg-[#ff8d65] disabled:opacity-60"
                onSignedIn={() => window.location.replace("/")}
                onCancel={() => setChallenge(null)}
              />
            </div>
          ) : (
          <form onSubmit={onSubmit} className="group mt-2">
            <div className="mt-8">
              <label htmlFor="chatter-username" className="block text-lg font-medium">Username</label>
              <input
                id="chatter-username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder={isRegister ? "name.chatter" : "name.not-an-email"}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                required
                minLength={3}
                maxLength={32}
                pattern="[a-zA-Z0-9_.\-]{3,32}"
                className={`peer ${INPUT} mt-3`}
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
              <label htmlFor="chatter-password" className="block text-lg font-medium">Password</label>
              <div className="relative mt-3">
                <input
                  id="chatter-password"
                  type={showPw ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={isRegister ? "Create a password" : "Password"}
                  autoComplete={isRegister ? "new-password" : "current-password"}
                  required
                  minLength={6}
                  className={`${INPUT} pr-16`}
                />
                <button
                  type="button"
                  onClick={() => setShowPw((v) => !v)}
                  aria-pressed={showPw}
                  aria-controls="chatter-password"
                  className="absolute inset-y-0 right-0 flex w-14 items-center justify-center rounded-r-xl text-white/85 hover:text-white focus-visible:outline-2 focus-visible:outline-accent"
                >
                  {showPw ? <EyeIcon /> : <EyeOffIcon />}
                  <span className="sr-only">Show password</span>
                </button>
              </div>
              {isRegister && <p className={HINT}>Must be at least 6 characters</p>}
            </div>

            {isRegister && (
              <div className="mt-6">
                <label htmlFor="chatter-display-name" className="block text-lg font-medium">
                  Display name <span className="font-normal text-fg-dim">(optional)</span>
                </label>
                <input
                  id="chatter-display-name"
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="What your owner calls you"
                  maxLength={64}
                  className={`${INPUT} mt-3`}
                />
              </div>
            )}

            {error && (
              <p role="alert" className={`flex ${PINK} mt-6`}>
                <Bang />
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy || (isRegister && invitePreview.data?.used === true)}
              className="mt-8 flex h-14 w-full items-center justify-center rounded-xl bg-accent text-lg font-medium text-[#0c0c0c] hover:bg-[#ff8d65] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60 group-invalid:bg-[#4a2a20] group-invalid:text-[#c4a598] motion-safe:transition-colors"
            >
              {busy ? "…" : isRegister ? "Accept invite & join" : "Sign in"}
            </button>
          </form>
          )}

          {/* Returning chatter? Owner signing in? Pointer to the other surface. */}
          <p className="mt-8 text-base text-white/85">
            {isRegister ? (
              <>
                Already joined?{" "}
                <a href="/chatter-login" className={LINK}>Sign in</a>
              </>
            ) : (
              <>
                Owner sign-in? <a href="/login" className={LINK}>Use the main login</a>.
              </>
            )}
          </p>

          {/* Desktop app. Gated behind sm: an installer is no use on a phone,
              and offering one there is just a dead end. Not in the app itself. */}
          {!inApp && <a
            href="/download"
            className="mt-8 hidden w-full items-center gap-4 rounded-2xl bg-white/[0.06] px-5 py-4 hover:bg-white/[0.09] focus-visible:outline-2 focus-visible:outline-accent sm:flex"
          >
            <span aria-hidden="true" className="text-xl leading-none text-accent">&#8595;</span>
            <span className="grid gap-0.5">
              <span className="text-base font-medium">Get the desktop app</span>
              <span className="text-sm text-fg-dim">
                Mac &amp; Windows &mdash; keeps your inbox live in the background.
              </span>
            </span>
          </a>}
        </section>

        <section aria-labelledby="chatter-pitch" className="md:pt-6">
          <h2 id="chatter-pitch" className="text-[clamp(2.25rem,4vw,3.75rem)] leading-[1.08] font-semibold tracking-tight text-balance">
            Chat smarter. Sleep occasionally.
          </h2>
          <p className="mt-6 max-w-xl text-xl text-pretty text-white/90">
            Your owner already connected the creators. You bring the charm; {BRAND_NAME} brings the inbox, the vault and
            the scheduled messages, in one tab instead of eleven.
          </p>

          {/* Fake shift card, the parody of their "your shift" widget. */}
          <div aria-label="Your shift (a joke)" role="group" className="mt-10 max-w-md rounded-2xl border border-white/10 bg-[#0c0c0c] p-6">
            <div className="flex items-center justify-between">
              <p className="text-lg font-medium">Your shift</p>
              <span className="flex items-center gap-2 rounded-full bg-accent/15 px-3 py-1 text-sm font-medium text-accent">
                <span aria-hidden="true" className="size-2 rounded-full bg-accent motion-safe:animate-pulse" />
                Starts now
              </span>
            </div>
            <dl className="mt-5 grid grid-cols-[auto_1fr] gap-x-6 gap-y-3 text-base">
              <dt className="text-fg-dim">Ends</dt>
              <dd>When the fans log off (they don&apos;t)</dd>
              <dt className="text-fg-dim">Breaks</dt>
              <dd>See Terms of Service</dd>
              <dt className="text-fg-dim">Commission</dt>
              <dd>{owner ? <>Ask <span>@{owner}</span></> : "Ask your owner"}</dd>
            </dl>
            <p className="mt-5 border-t border-white/10 pt-4 text-sm text-fg-dim">
              Not a real schedule. Real shifts live in Employees, under Shifts.
            </p>
          </div>
        </section>
      </div>
      <Notice />
    </main>
  );
}

const DEAD_CARD = "mt-8 rounded-2xl bg-[#ff5c9a]/[0.08] p-5 text-lg";
const LINK = "font-medium text-accent hover:underline hover:underline-offset-4 focus-visible:outline-2 focus-visible:outline-accent";
