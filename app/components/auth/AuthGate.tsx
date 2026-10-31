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
 * stable and the post-login redirect target is whatever the user asked.
 * If the user probe could not reach the relay at boot (and no chatter is
 * signed in), a retry screen instead of <Landing>.
 *
 * While the probes run, a browser that holds a session cookie (`signedIn`, read by the root layout on the server)
 * sees the route's BootSkeleton, from the server's HTML on, instead of a blank page; one without sees nothing until
 * the probes answer, so a signed-out visitor never sees the app's frame flash before the landing.
 */

import { usePathname } from "next/navigation";

import { useUser } from "@/contexts/UserContext";
import { gateScreen } from "@/contexts/userSessionReducer";
import { useChatter } from "@/contexts/ChatterContext";
import Landing from "@/components/auth/Landing";
import ChatterLogin from "@/components/auth/ChatterLogin";
import ShareReport from "@/components/growth/ShareReport";
import BootSkeleton from "@/components/shell/BootSkeleton";
import { EmptyState } from "@/components/ui/infloww";

export default function AuthGate({ children, signedIn = false }: { children: React.ReactNode; signedIn?: boolean }) {
  const { user, boot, retry } = useUser();
  const { chatter, loading: chatterLoading, reprobe } = useChatter();
  const pathname = usePathname();

  // The sign-in form is bare for everyone: a signed-in owner can still sign in
  // as someone else, and the submit's router.replace(next) lands in the shell.
  if (pathname === "/login") return <Landing />;
  // The employee invite page is bare for everyone: an owner opening an invite
  // link on their own browser gets the invite screen, not their shell.
  if (pathname === "/chatter-login") return <ChatterLogin />;
  // A share link's report is public: no sign-in, no shell.
  if (pathname?.startsWith("/share/")) return <ShareReport />;
  // Wait for BOTH probes to settle so we don't flash <Landing> before
  // chatter detection completes (or vice versa).
  switch (gateScreen({ user, boot }, { present: !!chatter, loading: chatterLoading })) {
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
    case "login": return <Landing />;
  }
}
