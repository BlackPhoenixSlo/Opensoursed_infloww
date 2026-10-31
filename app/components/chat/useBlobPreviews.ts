"use client";

/**
 * useBlobPreviews — the Composer's tiles' blob previews. Media a change drops
 * take their previews with them, unless a remaining tile (from the same file)
 * still shows one, a send took them (`markSent`: the optimistic bubble shows
 * it until the server copy arrives), or a held refused offer still shows them
 * (./refusedOffers `revokeUnlessHeld`). The chat closing revokes the rest.
 */

import { useEffect, useRef } from "react";

import type { VaultMedia } from "@/lib/relay";

import { previewsToRevoke } from "./composerSubmit";
import { revokeUnlessHeld } from "./refusedOffers";

export function useBlobPreviews(attached: VaultMedia[]) {
  const shownRef = useRef(attached);
  const sentRef = useRef(new Set<string>());
  useEffect(() => {
    // A sent preview back on a tile (a restore) is the tiles' again.
    attached.forEach((m) => m._localPreview && sentRef.current.delete(m._localPreview));
    revokeUnlessHeld(previewsToRevoke(shownRef.current, attached, sentRef.current));
    shownRef.current = attached;
  }, [attached]);
  useEffect(() => () => revokeUnlessHeld(shownRef.current.map((m) => m._localPreview)), []);
  return {
    /** A send took these tiles: their previews stay for its bubble. */
    markSent(media: readonly VaultMedia[]) {
      media.forEach((m) => m._localPreview && sentRef.current.add(m._localPreview));
    },
    /** These were revoked elsewhere (a dismissed or dropped offer). */
    forget(urls: readonly string[]) {
      urls.forEach((u) => sentRef.current.delete(u));
    },
  };
}
