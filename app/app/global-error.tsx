"use client";

import "./globals.css";
import { useEffect } from "react";

import { EmptyState } from "@/components/ui/infloww";
import { reportError } from "@/lib/errorReporter";

/** A crash in the root layout itself (page crashes stay with `ErrorBoundary` in providers, which reports them): it replaces <html>, so it brings the stylesheet and reads the saved theme. */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { reportError(error, "react-render", { scope: "global" }); }, [error]);
  let theme: "light" | undefined;
  try { if (localStorage.getItem("chatterly:theme") === "light") theme = "light"; } catch { /* no storage (server, blocked): dark */ }
  return (
    <html lang="en" data-theme={theme}>
      <body className="grid min-h-screen place-items-center bg-bg p-6 text-fg">
        <EmptyState kind="error" text="Something went wrong." textClassName="text-fg-dim" onRetry={reset} />
      </body>
    </html>
  );
}
