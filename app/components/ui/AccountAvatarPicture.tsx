"use client";

/**
 * AccountAvatarPicture — a Creator's OF profile avatar, filling its parent
 * box. On a miss (no avatar yet, OF 404, broken session, a broken image) it
 * degrades to the nickname's first letters on the Creator's colour, so it is
 * always *something*. The parent sets the box (size, radius, ring); the caller
 * sets how many letters show (`letters`) and their type (`initialClassName`).
 * Shared by the roster's avatar slot (one letter), the Messages Pro Creator
 * tabs (two, as the Clone's tab avatar, messages.js:266), and the Manage
 * creators table (none: a plain colour fill, when no Display image is picked).
 */

import { useEffect, useRef, useState } from "react";

import { useAccountAvatar, pickAvatarUrl, ownAvatar, fetchOwnProfile, type AccountAvatar } from "@/hooks/useAccountAvatar";
import { type AccountMeta } from "@/lib/relay";

/** What the picture reads off an account: a placeholder for a Creator the roster doesn't hold yet fits too. */
export type AvatarAccount = Pick<AccountMeta, "id" | "nickname" | "color">;
import { onAccountSessionCaptured } from "@/lib/accountSession";
import { proxyImage } from "@/lib/mediaUrl";
import { cn } from "@/lib/utils";

type PictureProps = { account: AvatarAccount; letters: 0 | 1 | 2; initialClassName: string };
export type AvatarHealth = { profile?: AccountAvatar | null; settled: boolean };

export function AccountAvatarPicture({ health, ...props }: PictureProps & { health?: AvatarHealth }) {
  const verified = ownAvatar(health?.profile, props.account.id);
  // Observe the full-profile cache while health is pending, without starting a
  // duplicate read. A verified empty health avatar overrides an old cached face.
  const q = useAccountAvatar(props.account.id, !health || (health.settled && !verified));
  const rawUrl = pickAvatarUrl(verified ?? q.data);
  return <Picture key={JSON.stringify([props.account.id, rawUrl])} {...props} rawUrl={rawUrl} recoveryEnabled={!health || health.settled} />;
}

/** A source/account change remounts this one-shot recovery. Keep recovery local:
 * neither a health projection nor an image retry overwrites the shared profile. */
function Picture({ account, letters, initialClassName, rawUrl, recoveryEnabled }: PictureProps & {
  rawUrl: string | null; recoveryEnabled: boolean;
}) {
  const [recovered, setRecovered] = useState<string | null | undefined>();
  const [broken, setBroken] = useState(false);
  const recovery = useRef<AbortController | null>(null);
  useEffect(() => {
    const unsubscribe = onAccountSessionCaptured(account.id, () => {
      // Abort synchronously, before a late transport completion can publish.
      // Ordinary health invalidation is not a new session or a new budget.
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
    // A cached image can fail before health answers. Let that existing read
    // finish first; a new verified URL remounts Picture without a recovery read.
    if (!broken || !recoveryEnabled || recovery.current) return;
    const controller = new AbortController();
    recovery.current = controller;
    void fetchOwnProfile<AccountAvatar>(account.id, controller.signal).then((profile) => {
      if (controller.signal.aborted) return;
      const next = pickAvatarUrl(ownAvatar(profile, account.id));
      setRecovered(next);
      // Retrying an identical failed URL would only repeat the error.
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
