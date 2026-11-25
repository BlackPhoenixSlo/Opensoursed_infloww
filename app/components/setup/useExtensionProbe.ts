"use client";


import { useEffect, useState } from "react";

export const EXTENSION_ID = "anjjmiahkfondbhahocpkehjjabkommc";
const EXTENSION_PROBE_URL = `chrome-extension://${EXTENSION_ID}/icons/icon16.png`;

export function useExtensionProbe(): boolean | null {
  const [extInstalled, setExtInstalled] = useState<boolean | null>(null);

  useEffect(() => {
    // The browser's "Fetch API cannot load chrome-extension://" log is matched by the route walk's CONSOLE_ALLOW: keep URL and call unchanged.
    let cancelled = false;
    fetch(EXTENSION_PROBE_URL, { method: "GET", cache: "no-store" })
      .then((r) => { if (!cancelled) setExtInstalled(r.ok); })
      .catch(() => { if (!cancelled) setExtInstalled(false); });
    return () => { cancelled = true; };
  }, []);

  return extInstalled;
}
