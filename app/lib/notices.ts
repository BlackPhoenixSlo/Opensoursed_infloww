"use client";


export interface Notice {
  id: string;
  text: string;
  label: string;
}

const listeners = new Set<(n: Notice) => void>();

export function pushNotice(n: Notice): void {
  for (const fn of listeners) fn(n);
}

export function onNotice(fn: (n: Notice) => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}
