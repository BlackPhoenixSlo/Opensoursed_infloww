"use client";


import { useEffect, useRef, useState } from "react";

export interface KeyDraft {
  draft: Record<string, string>;
  dirty: boolean;
  setField: (name: string, value: string) => void;
  save: () => Promise<void>;
  clear: (name: string) => Promise<void>;
  note: string | null;
}

export function useKeyDraft(
  submit: (values: Record<string, string>) => Promise<unknown>,
  savedNote: string,
): KeyDraft {
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [note, setNote] = useState<string | null>(null);

  // Trim is load-bearing: servers decide with .strip(), so a space-only field would otherwise overwrite the stored key like an empty one.
  const typed = Object.fromEntries(
    Object.entries(draft).filter(([, v]) => v.trim() !== ""),
  );

  const noteTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (noteTimer.current) clearTimeout(noteTimer.current);
  }, []);

  function flashNote(msg: string) {
    if (noteTimer.current) clearTimeout(noteTimer.current);
    setNote(msg);
    noteTimer.current = setTimeout(() => setNote(null), 3000);
  }

  function stickNote(msg: string) {
    if (noteTimer.current) clearTimeout(noteTimer.current);
    setNote(msg);
  }

  function setField(name: string, value: string) {
    setDraft((d) => ({ ...d, [name]: value }));
  }

  function drop(name: string) {
    setDraft((d) => {
      const { [name]: _drop, ...rest } = d;
      return rest;
    });
  }

  async function save() {
    setNote(null);
    const sending = typed;
    const names = Object.keys(sending);
    if (!names.length) return;
    try {
      await submit(sending);
      setDraft((d) => {
        const rest = { ...d };
        // Drop only what was sent: text typed during the request is a real unsaved edit.
        for (const n of names) if (rest[n] === sending[n]) delete rest[n];
        return rest;
      });
      flashNote(savedNote);
    } catch (e) {
      stickNote(e instanceof Error ? e.message : "Save failed");
    }
  }

  async function clear(name: string) {
    setNote(null);
    try {
      await submit({ [name]: "" });
      drop(name);
      flashNote("Cleared.");
    } catch (e) {
      stickNote(e instanceof Error ? e.message : "Clear failed");
    }
  }

  return { draft, dirty: Object.keys(typed).length > 0, setField, save, clear, note };
}
