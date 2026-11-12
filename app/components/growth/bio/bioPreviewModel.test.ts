import { describe, expect, it } from "vitest";

import type { BioLink } from "@/hooks/useBioPages";
import { INITIAL_LINK, bioLinkReducer, type Action } from "@/components/growth/bio/bioLinkForm";
import { bgAspectRatio, draftLinkView, previewModel, trackingRows, trackingUrl, type PreviewProfile } from "@/components/growth/bio/bioPreviewModel";

const link = (id: string, over: Partial<BioLink> = {}): BioLink => ({
  id, link_id: id.slice(0, 12), title: `Link ${id}`, destination: "https://x.test", icon: "", icon_stock: null,
  icon_url: "", background_image: "", background_url: "", is_adult: false, mode: "", tracking: false,
  default_tracking_code: "", geo: null, sort_order: 0, updated_at: "", ...over,
});
const PROFILE: PreviewProfile = { displayName: "Alice", bio: "", verified: false, mode: "direct", avatarUrl: "" };
const form = (actions: Action[]) => actions.reduce(bioLinkReducer, INITIAL_LINK);

describe("previewModel mode", () => {
  it.each<[string, string, string]>([
    ["", "direct", "direct"],
    ["junk", "direct", "direct"],
    ["escape_ig", "direct", "escape_ig"],
    ["", "junk", "escape_ig"],
  ])("link %j on profile %j → %j", (linkMode, profileMode, want) => {
    const m = previewModel({ ...PROFILE, mode: profileMode }, [link("a", { mode: linkMode })]);
    expect(m.links[0].mode).toBe(want);
  });
});

describe("previewModel cards", () => {
  it.each<[boolean, string]>([[true, "Exclusive Content"], [false, "Social Media"]])("adult %s → %j", (adult, sub) => {
    expect(previewModel(PROFILE, [link("a", { is_adult: adult })]).links[0].subtitle).toBe(sub);
  });

  it("an icon without a background is hidden; with one it shows", () => {
    const m = previewModel(PROFILE, [
      link("a", { icon_url: "/i.webp" }),
      link("b", { icon_url: "/i.webp", background_url: "/bg.webp" }),
    ]);
    expect(m.links.map((l) => l.iconUrl)).toEqual(["", "/i.webp"]);
  });

  it("the open link's draft replaces its saved card in place", () => {
    const links = [link("a"), link("b")];
    const draft = draftLinkView(form([{ type: "open_edit", link: links[0] }, { type: "set", patch: { title: "Edited" } }]), null);
    expect(previewModel(PROFILE, links, draft).links.map((l) => l.title)).toEqual(["Edited", "Link b"]);
  });

  it("a new link's draft goes last", () => {
    const draft = draftLinkView(form([{ type: "open_new" }, { type: "set", patch: { title: "New" } }]), null);
    expect(previewModel(PROFILE, [link("a")], draft).links.map((l) => [l.key, l.title])).toEqual([
      ["a", "Link a"], ["new", "New"],
    ]);
  });

  it("the draft's picked background and stock icon show; Remove drops the saved background", () => {
    const saved = link("a", { background_url: "/bg.webp" });
    const picked = draftLinkView(form([{ type: "open_edit", link: saved }, { type: "set", patch: { icon: "igicon" } }]), "blob:1");
    expect(picked).toMatchObject({ backgroundUrl: "blob:1", iconUrl: "/admin/bio-pages/stock/igicon.webp" });
    const removed = draftLinkView(form([{ type: "open_edit", link: saved }, { type: "remove_bg", on: true }]), null);
    expect(removed?.backgroundUrl).toBe("");
    expect(draftLinkView(INITIAL_LINK, null)).toBeUndefined();
  });
});

describe("trackingUrl", () => {
  it("keeps coded active links only", () => {
    const links = [
      { id: 1, code: 123, name: "Live", is_deleted: false },
      { id: 2, code: null, name: "No code", is_deleted: false },
      { id: 3, code: 456, name: "Deleted", is_deleted: true },
    ];
    expect(trackingRows(links, "/alice")).toEqual([{ key: "1-123", name: "Live", code: "123", url: "/alice/123" }]);
  });
  it.each([
    ["http://127.0.0.1:9/u", "123", "http://127.0.0.1:9/u/123"],
    ["https://d/", "123", "https://d/123"],
    ["/alice", "geo", "/alice/geo"],
  ])("%j + %j → %j", (base, code, want) => expect(trackingUrl(base, code)).toBe(want));
});

describe("bgAspectRatio", () => {
  it.each<[string, Parameters<typeof bgAspectRatio>[0], string]>([
    ["not loaded yet", null, "2.5 / 1"],
    ["square photo", { width: 800, height: 800 }, "1 / 1"],
    ["portrait photo", { width: 600, height: 900 }, `${600 / 900} / 1`],
    ["wide banner", { width: 1500, height: 500 }, "3 / 1"],
    ["zero height", { width: 800, height: 0 }, "2.5 / 1"],
  ])("%s", (_name, size, want) => {
    expect(bgAspectRatio(size)).toBe(want);
  });
});
