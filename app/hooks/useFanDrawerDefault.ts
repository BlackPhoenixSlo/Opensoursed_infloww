"use client";


import { createStoredFlag } from "@/lib/storageSync";

const STORAGE_KEY = "chatterly:fan-drawer-default-open";
const EVENT = "chatterly-fan-drawer-default-change";

export const { read: readFanDrawerDefault, use: useFanDrawerDefault } = createStoredFlag(STORAGE_KEY, EVENT, true);
