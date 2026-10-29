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
 *
 * While the probes run, a browser that holds a session cookie (`signedIn`, read by the root layout on the server)
 * sees the route's BootSkeleton, from the server's HTML on, instead of a blank page; one without sees nothing until
 * the probes answer, so a signed-out visitor never sees the app's frame flash before the landing.
 */

import { usePathname } from "next/navigation";

import { useUser } from "@/contexts/UserContext";
import { useChatter } from "@/contexts/ChatterContext";
import Landing from "@/components/auth/Landing";
import ChatterLogin from "@/components/auth/ChatterLogin";
import ShareReport from "@/components/growth/ShareReport";
import BootSkeleton from "@/components/shell/BootSkeleton";

export default function AuthGate({ children, signedIn = false }: { children: React.ReactNode; signedIn?: boolean }) {
  const { user, loading: userLoading } = useUser();
  const { chatter, loading: chatterLoading } = useChatter();
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
  if (userLoading || chatterLoading) return signedIn ? <BootSkeleton pathname={pathname ?? "/"} /> : null;
  if (user || chatter) return <>{children}</>;
  return <Landing />;
}
