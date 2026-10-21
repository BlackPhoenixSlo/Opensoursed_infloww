import { describe, expect, it } from "vitest";

import { scriptDraftFromMessage, scriptPickWarning } from "@/lib/messageScripts";
import type { PickedTemplate } from "@/components/chat/TemplatePicker";
import type { FanVaultEntry } from "@/hooks/useFanVaultHistory";
import type { OFMessage } from "@/lib/relay";

const sent = (over: Partial<OFMessage>): OFMessage =>
  ({ id: 1, text: "", fromUser: { id: 555 }, createdAt: "2026-06-04T12:00:00Z", media: [], ...over }) as OFMessage;

const tpl = (over: Partial<PickedTemplate>): PickedTemplate => ({
  source: "local", text: "hi", displayText: "hi", mediaCount: 0, price: 0, lockedText: false,
  isWelcome: false, media: [], previews: [], taggedUsers: [], ...over,
});

const bought = (was_purchased: boolean): FanVaultEntry => ({
  send_count: 1, last_sent_at: null, last_price_cents: 0, was_purchased, last_purchase_at: null, total_paid_cents: 0,
});

describe("scriptDraftFromMessage (Save as script, roadmap W4 4.2)", () => {
  it("keeps a PPV's text, price, locked text and media, free previews first so the composer reads them as free", () => {
    const d = scriptDraftFromMessage(sent({
      text: "<p>new set<br>just for you</p>", price: 15, lockedText: true, previews: [22],
      media: [
        { id: 11, type: "photo", files: { thumb: { url: "https://cdn/t.jpg" }, full: { url: null as unknown as string } } },
        { id: 22, type: "video" }, { id: "900715634200489987abc", type: "photo" },
      ],
    }));
    expect(d.text).toBe("new set\njust for you");
    expect(d.title).toBe("new set");
    expect(d.price).toBe(15);
    expect(d.lockedText).toBe(true);
    expect(d.media!.map((m) => m.id)).toEqual([22, 11]);
    expect(d.previews).toEqual([22]);
    // Vault files keep only variants with a url; a media item without files has none.
    expect(d.media![1].files).toEqual({ thumb: { url: "https://cdn/t.jpg" }, preview: undefined,
                                        squarePreview: undefined, full: undefined });
    expect(d.media![0].files).toBeNull();
  });

  it("a free message saves free: no price, no locked text, no previews; a GIF rides along", () => {
    const d = scriptDraftFromMessage(sent({ text: "hey", lockedText: true, previews: [5], giphyId: "abc" }));
    expect(d).toMatchObject({ price: 0, lockedText: false, previews: [], gifId: "abc" });
    expect(d.gifUrl).toContain("abc");
  });
});

describe("scriptPickWarning (the 'Use script?' guard)", () => {
  const media = [{ id: 1, type: "photo" }, { id: 2, type: "photo" }];

  it("says nothing for a script with no bought and no deleted media", () => {
    expect(scriptPickWarning(tpl({ media }), { "1": bought(false) })).toBeNull();
    expect(scriptPickWarning(tpl({ media }), undefined)).toBeNull();
  });

  it("counts the media this Fan already bought", () => {
    expect(scriptPickWarning(tpl({ media }), { "2": bought(true) }))
      .toContain("already bought 1 of the 2 media");
    expect(scriptPickWarning(tpl({ media }), { "1": bought(true), "2": bought(true) }))
      .toContain("already bought the media in this script");
  });

  it("warns about media deleted from the vault, with or without a Fan", () => {
    expect(scriptPickWarning(tpl({ media, removedMediaIds: [2] }), undefined))
      .toContain("deleted from the vault");
  });
});
