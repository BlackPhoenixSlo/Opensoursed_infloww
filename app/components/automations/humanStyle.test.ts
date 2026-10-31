import { describe, expect, it } from "vitest";

import type { StyleConfig } from "@/hooks/useStyleConfig";
import { dropSaved } from "./humanStyle";

describe("dropSaved", () => {
  it.each<{ name: string; edits: StyleConfig; sent: StyleConfig; want: StyleConfig }>([
    { name: "nothing toggled in flight: all dropped",
      edits: { autoreply: false, typos_autoreply: true }, sent: { autoreply: false, typos_autoreply: true }, want: {} },
    { name: "a new box toggled in flight survives",
      edits: { autoreply: false, typos_autoreply: false }, sent: { autoreply: false }, want: { typos_autoreply: false } },
    { name: "the sent box flipped back in flight survives",
      edits: { autoreply: true }, sent: { autoreply: false }, want: { autoreply: true } },
    { name: "no edits", edits: {}, sent: { autoreply: false }, want: {} },
  ])("$name", ({ edits, sent, want }) => {
    expect(dropSaved(edits, sent)).toEqual(want);
  });
});
