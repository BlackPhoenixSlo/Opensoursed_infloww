"use client";


import { createStoredFlag } from "@/lib/storageSync";

const STORAGE_KEY = "chatterly:compact-media";
const EVENT = "chatterly-compact-media-change";

export const { read: readCompactMedia, use: useCompactMedia } = createStoredFlag(STORAGE_KEY, EVENT, true);
