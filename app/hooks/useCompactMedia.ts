"use client";

/**
 * useCompactMedia — persisted "shrink chat media previews" toggle.
 *
 * Off (default): photos/videos/GIFs render at the normal in-bubble size
 * (max-h ~48 / max-w ~260).
 * On: previews are smaller (max-h ~32 / max-w ~160) so long chats with
 * lots of attached media stay scannable without all the scrolling.
 *
 * Same custom-event + storage-event pattern as useBlurMode so multiple
 * mounted bubbles re-render in sync after a flip.
 */

import { createStoredFlag } from "@/lib/storageSync";

const STORAGE_KEY = "chatterly:compact-media";
const EVENT = "chatterly-compact-media-change";

// Default ON; off is stored as "0", on removes the key.
export const { read: readCompactMedia, use: useCompactMedia } = createStoredFlag(STORAGE_KEY, EVENT, true);
