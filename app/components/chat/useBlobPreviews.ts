"use client";


import { useEffect, useRef } from "react";

import type { VaultMedia } from "@/lib/relay";

import { previewsToRevoke } from "./composerSubmit";
import { revokeUnlessHeld } from "./refusedOffers";

export function useBlobPreviews(attached: VaultMedia[]) {
  const shownRef = useRef(attached);
  const sentRef = useRef(new Set<string>());
  useEffect(() => {
    attached.forEach((m) => m._localPreview && sentRef.current.delete(m._localPreview));
    revokeUnlessHeld(previewsToRevoke(shownRef.current, attached, sentRef.current));
    shownRef.current = attached;
  }, [attached]);
  useEffect(() => () => revokeUnlessHeld(shownRef.current.map((m) => m._localPreview)), []);
  return {
    markSent(media: readonly VaultMedia[]) {
      media.forEach((m) => m._localPreview && sentRef.current.add(m._localPreview));
    },
    forget(urls: readonly string[]) {
      urls.forEach((u) => sentRef.current.delete(u));
    },
  };
}
