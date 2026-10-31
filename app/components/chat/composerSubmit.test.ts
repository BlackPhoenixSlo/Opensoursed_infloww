import { describe, expect, it } from "vitest";

import type { VaultMedia } from "@/lib/relay";

import { gifPlan, previewsToRevoke, scheduledToast } from "./composerSubmit";
import type { PickedGif } from "./GifPicker";

const gif = (id: string): PickedGif => ({ id, thumbUrl: `t/${id}`, fullUrl: `f/${id}` });
const media = (id: number, preview?: string): VaultMedia => ({ id, type: "photo", _localPreview: preview });

describe("gifPlan", () => {
  it.each<[string, PickedGif[], string | undefined, string[]]>([
    ["no GIF", [], undefined, []],
    ["one rides on the send", [gif("a")], "a", []],
    ["the rest trail, in pick order", [gif("a"), gif("b"), gif("c")], "a", ["b", "c"]],
  ])("%s", (_n, picked, first, trailing) => {
    const plan = gifPlan(picked);
    expect(plan.first?.id).toBe(first);
    expect(plan.trailing.map((g) => g.id)).toEqual(trailing);
  });
});

describe("scheduledToast", () => {
  const now = Date.UTC(2026, 9, 31, 12, 0, 0);
  const at = (mins: number) => new Date(now + mins * 60_000).toISOString();
  it.each<[string, string, string]>([
    ["within the executor's window: minutes", at(5), "⏱ Scheduled · sending in 5 min (saved — survives reload)"],
    ["at the window's edge still the executor's", at(15), "⏱ Scheduled · sending in 15 min (saved — survives reload)"],
    ["a time already due reads 1 min", at(-2), "⏱ Scheduled · sending in 1 min (saved — survives reload)"],
    ["past it: queued on OF", at(16), `⏱ Queued on OF for ${new Date(at(16)).toLocaleString()}`],
  ])("%s", (_n, scheduledAt, want) => {
    expect(scheduledToast(scheduledAt, now, 15)).toBe(want);
  });
});

describe("previewsToRevoke", () => {
  it.each<[string, VaultMedia[], VaultMedia[], string[], string[]]>([
    ["a dropped tile's preview goes", [media(1, "blob:1"), media(2, "blob:2")], [media(2, "blob:2")], [], ["blob:1"]],
    ["kept while another tile shows it", [media(1, "blob:1")], [media(3, "blob:1")], [], []],
    ["kept while a send's bubble shows it", [media(1, "blob:1")], [], ["blob:1"], []],
    ["tiles without one revoke nothing", [media(1)], [], [], []],
    ["nothing dropped", [media(1, "blob:1")], [media(1, "blob:1")], [], []],
  ])("%s", (_n, prev, live, sent, want) => {
    expect(previewsToRevoke(prev, live, new Set(sent))).toEqual(want);
  });
});
