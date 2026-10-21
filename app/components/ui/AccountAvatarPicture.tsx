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

import { useState } from "react";

import { useAccountAvatar, pickAvatarUrl } from "@/hooks/useAccountAvatar";
import { type AccountMeta } from "@/lib/relay";

/** What the picture reads off an account: a placeholder for a Creator the roster doesn't hold yet fits too. */
export type AvatarAccount = Pick<AccountMeta, "id" | "nickname" | "color">;
import { proxyImage } from "@/lib/mediaUrl";
import { cn } from "@/lib/utils";

export function AccountAvatarPicture({
  account, letters, initialClassName,
}: { account: AvatarAccount; letters: 0 | 1 | 2; initialClassName: string }) {
  const q = useAccountAvatar(account.id);
  const rawUrl = pickAvatarUrl(q.data);
  const url = proxyImage(rawUrl, account.id);
  const [broken, setBroken] = useState(false);

  const initial = (account.nickname || account.id || "?").trim().slice(0, letters).toUpperCase();

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
