"use client";

/**
 * useFanDrawerDefault — persisted flag that auto-opens the FanDrawer on
 * every chat-select when enabled. Toggled from inside the drawer itself
 * via a small "Keep open by default" checkbox, so the user can opt in
 * once and never have to click the header again.
 */

import { createStoredFlag } from "@/lib/storageSync";

const STORAGE_KEY = "chatterly:fan-drawer-default-open";
const EVENT = "chatterly-fan-drawer-default-change";

// Default ON; off is stored as "0", on removes the key.
export const { read: readFanDrawerDefault, use: useFanDrawerDefault } = createStoredFlag(STORAGE_KEY, EVENT, true);
