"use client";


import { useEffect, useRef, useState } from "react";

import { useAccountAvatar, pickAvatarUrl, ownAvatar, fetchOwnProfile, type AccountAvatar } from "@/hooks/useAccountAvatar";
import { type AccountMeta } from "@/lib/relay";

export type AvatarAccount = Pick<AccountMeta, "id" | "nickname" | "color">;
import { onAccountSessionCaptured } from "@/lib/accountSession";
import { proxyImage } from "@/lib/mediaUrl";
import { cn } from "@/lib/utils";

type PictureProps = { account: AvatarAccount; letters: 0 | 1 | 2; initialClassName: string };
export type AvatarHealth = { profile?: AccountAvatar | null; settled: boolean };

export function AccountAvatarPicture({ health, ...props }: PictureProps & { health?: AvatarHealth }) {
  const verified = ownAvatar(health?.profile, props.account.id);
  const q = useAccountAvatar(props.account.id, !health || (health.settled && !verified));
  const rawUrl = pickAvatarUrl(verified ?? q.data);
  return <Picture key={JSON.stringify([props.account.id, rawUrl])} {...props} rawUrl={rawUrl} recoveryEnabled={!health || health.settled} />;
}

function Picture({ account, letters, initialClassName, rawUrl, recoveryEnabled }: PictureProps & {
  rawUrl: string | null; recoveryEnabled: boolean;
}) {
  const [recovered, setRecovered] = useState<string | null | undefined>();
  const [broken, setBroken] = useState(false);
  const recovery = useRef<AbortController | null>(null);
  // Ordinary health invalidation is not a new session or a new recovery budget.
  useEffect(() => {
    const unsubscribe = onAccountSessionCaptured(account.id, () => {
      // Abort synchronously, before a late transport completion can publish.
      recovery.current?.abort();
      recovery.current = null;
      setRecovered(undefined);
      setBroken(false);
    });
    return () => { unsubscribe(); recovery.current?.abort(); };
  }, [account.id]);
  const url = proxyImage(recovered === undefined ? rawUrl : recovered, account.id);
  const initial = (account.nickname || account.id || "?").trim().slice(0, letters).toUpperCase();

  useEffect(() => {
    if (!broken || !recoveryEnabled || recovery.current) return;
    const controller = new AbortController();
    recovery.current = controller;
    void fetchOwnProfile<AccountAvatar>(account.id, controller.signal).then((profile) => {
      if (controller.signal.aborted) return;
      const next = pickAvatarUrl(ownAvatar(profile, account.id));
      setRecovered(next);
      setBroken(!next || next === rawUrl);
    });
  }, [account.id, rawUrl, recoveryEnabled, broken]);

  return url && !broken ? (
    <img
      src={url}
      alt=""
      loading="lazy"
      decoding="async"
      fetchPriority="low"
      onError={() => setBroken(true)}
      className="w-full h-full object-cover"
    />
  ) : (
    <span
      className={cn("w-full h-full grid place-items-center text-white", initialClassName)}
      style={{ background: account.color || "#666" }}
    >
      {initial}
    </span>
  );
}
