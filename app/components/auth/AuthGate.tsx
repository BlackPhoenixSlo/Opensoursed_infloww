"use client";

/**
 * AuthGate — wraps the authed app shell. If no principal is signed in,
 * render the landing page (or the chatter-login page when the URL is
 * /chatter-login).
 *
 * Two principals participate:
 *   • User cookie (owner / founder) — owner perspective wins everywhere.
 *   • Chatter cookie — second-class principal that drives the picker via
 *     ChatterContext when the User cookie is absent.
 *
 * /login renders the bare <Landing> for everyone, signed in or not, never
 * inside the shell (Infloww's "Add account" opens a bare login too); the
 * form self-redirects on submit.
 * /chatter-login renders <ChatterLogin> bare always, signed in or not (the
 * invite form there self-redirects to "/"). /share/* (a share link's public
 * report) renders <ShareReport> bare. All other routes: gate behind one of the two
 * principals; otherwise render <Landing> in place so the URL stays
 * stable. Its sign-in then goes to the Dashboard, except from an Ultra plan page
 * (`SIGN_IN_RETURNS`): an MCP client's open_url, so the owner lands back on that plan.
 * If the user probe could not reach the relay at boot (and no chatter is
 * signed in), a retry screen instead of <Landing>. If the proxy in front of
 * the relay answered 403, or the probe has not answered for ME_SLOW_MS, the
 * <Landing> at once with a banner over it (`[data-auth-blocked]`) whose Retry
 * re-probes /auth/me while the form stays mounted (what was typed is kept).
 *
 * While the probes run, a browser that holds a session cookie (`signedIn`, read by the root layout on the server)
 * sees the route's BootSkeleton, from the server's HTML on, instead of a blank page; one without sees nothing until
 * the probes answer, so a signed-out visitor never sees the app's frame flash before the landing. Such a browser's
 * Dashboard or Messages Pro screen bundle starts with the probes (the server's inline boot answers it when it guessed
 * the same screen).
 */

import { useEffect } from "react";
import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";

import { useUser } from "@/contexts/UserContext";
import { gateScreen } from "@/contexts/userSessionReducer";
import { useChatter } from "@/contexts/ChatterContext";
import Landing from "@/components/auth/Landing";
import BootSkeleton from "@/components/shell/BootSkeleton";
import { EmptyState } from "@/components/ui/infloww";
import type { AuthBanner } from "@/contexts/userSessionReducer";
import { prefetchScreenBundle } from "@/lib/relay";
import { bootScreen, cookieValue } from "@/lib/screenEntry";

const ChatterLogin = dynamic(() => import("@/components/auth/ChatterLogin"));
const ShareReport = dynamic(() => import("@/components/growth/ShareReport"));

/** In-place sign-in that returns to the page asked for (else the Dashboard, Landing's default). */
const SIGN_IN_RETURNS = ["/ultra/plans/"];
export const signInReturn = (pathname: string | null): string | undefined =>
  pathname && SIGN_IN_RETURNS.some((p) => pathname.startsWith(p)) ? pathname : undefined;

const BANNER_TEXT: Record<AuthBanner, string> = {
  blocked: "Proxy blocked (403)",
  slow: "Relay not answering",
};

export default function AuthGate({ children, signedIn = false }: { children: React.ReactNode; signedIn?: boolean }) {
  const { user, boot, banner, formUp, retry } = useUser();
  const { chatter, loading: chatterLoading, reprobe } = useChatter();
  const pathname = usePathname();
  useEffect(() => {
    if (!signedIn) return;
    const s = bootScreen(window.location.pathname + window.location.search, (n) => cookieValue(document.cookie, n));
    if (s) prefetchScreenBundle(s);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the document's first route only
  }, []);

  if (pathname === "/login") return <Landing />;
  if (pathname === "/chatter-login") return <ChatterLogin />;
  if (pathname?.startsWith("/share/")) return <ShareReport />;
  switch (gateScreen({ user, boot, formUp }, { present: !!chatter, loading: chatterLoading })) {
    case "loading": return signedIn ? <BootSkeleton pathname={pathname ?? "/"} /> : null;
    case "signed-in": return <>{children}</>;
    // The boot probe never reached the relay: nobody is known signed out, so no sign-in form.
    // Retry re-asks both principals: the chatter probe's null from the outage is cached too.
    case "retry": {
      const onRetry = () => { retry(); reprobe(); };
      return (
        <div className="min-h-screen grid place-items-center p-6" data-auth-unreachable>
          <EmptyState kind="error" text="Can't reach the server." onRetry={onRetry} />
        </div>
      );
    }
    case "login":
      return (
        <>
          {banner && (
            <div
              role="status"
              data-auth-blocked={banner}
              data-look="site"
              className="sticky top-0 z-10 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 border-b border-accent/40 bg-[#2a1a12] px-4 py-2 text-center text-sm text-white/90"
            >
              <span>{BANNER_TEXT[banner]}</span>
              <span aria-hidden="true">—</span>
              <button
                type="button"
                onClick={retry}
                disabled={boot === "probing"}
                className="font-medium text-accent hover:underline hover:underline-offset-4 focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-default disabled:opacity-50 disabled:no-underline"
              >
                Retry
              </button>
            </div>
          )}
          <Landing next={signInReturn(pathname)} />
        </>
      );
  }
}
