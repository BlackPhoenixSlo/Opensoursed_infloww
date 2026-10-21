"use client";

/**
 * useExtensionProbe — is the Chatterly Login Capture extension installed?
 *
 * The probe's one fetch site (docs/spec/infloww-parity-round-2/phase-04-creators-pages.md, Implementation Decisions).
 * Manage creators calls it once on mount and hands the result to the Add creator modal, so opening the modal never
 * probes again. The fetch, its URL, method and cache option are PasteCurlCard's old probe, unchanged: when the
 * extension is missing the browser logs "Fetch API cannot load chrome-extension://…", the message the Route walk's
 * `CONSOLE_ALLOW` line matches, so neither the URL nor the call may change.
 */

import { useEffect, useState } from "react";

export const EXTENSION_ID = "anjjmiahkfondbhahocpkehjjabkommc";
const EXTENSION_PROBE_URL = `chrome-extension://${EXTENSION_ID}/icons/icon16.png`;

/** null = checking, true = installed, false = not detected. */
export function useExtensionProbe(): boolean | null {
  const [extInstalled, setExtInstalled] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Detect the extension by fetching a web_accessible_resource it exposes.
    // 200 → installed (and exposing the icon). Network error → not installed
    // OR the user is on a pre-1.2.0 version that doesn't expose icons yet.
    fetch(EXTENSION_PROBE_URL, { method: "GET", cache: "no-store" })
      .then((r) => { if (!cancelled) setExtInstalled(r.ok); })
      .catch(() => { if (!cancelled) setExtInstalled(false); });
    return () => { cancelled = true; };
  }, []);

  return extInstalled;
}
