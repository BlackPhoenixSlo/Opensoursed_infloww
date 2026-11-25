"use client";


import { use, useEffect, useState } from "react";

import { relay } from "@/lib/relay";

interface MinUser {
  id?: number | string;
  username?: string;
  name?: string;
}

export default function ChatByUsernamePage({
  params,
}: {
  params: Promise<{ accountId: string; username: string }>;
}) {
  const { accountId, username } = use(params);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const u = await relay.get<MinUser>(
          `/api/of/v2/users/${encodeURIComponent(username)}`,
          { accountId },
        );
        if (cancelled) return;
        const id = u?.id;
        if (id == null) {
          setError(`Couldn't resolve @${username} on this account.`);
          return;
        }
        // Carry the query string: tip/purchase toasts append ?refresh=media, read on mount by the canonical page.
        window.location.replace(
          `/messages-pro/${encodeURIComponent(accountId)}/${encodeURIComponent(String(id))}${window.location.search}`,
        );
      } catch (e) {
        if (cancelled) return;
        setError((e as Error)?.message || `Lookup failed for @${username}.`);
      }
    })();
    return () => { cancelled = true; };
  }, [accountId, username]);

  return (
    <div className="min-h-dvh grid place-items-center p-6 text-fg-dim">
      {error ? (
        <div className="max-w-md text-center text-sm">
          <div className="text-fg mb-2">Couldn&apos;t open chat</div>
          <div>{error}</div>
        </div>
      ) : (
        <div className="text-sm">Opening chat with @{username}…</div>
      )}
    </div>
  );
}
