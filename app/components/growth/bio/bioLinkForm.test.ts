import { describe, expect, it } from "vitest";

import type { BioLink } from "@/hooks/useBioPages";
import {
  CODE_MSG, DEST_EMPTY_MSG, DEST_MSG, INITIAL_LINK, TITLE_MSG, bioLinkReducer, buildLinkPayload,
  canSubmit, draftOfLink, isDirty, linkFormError, type Action, type BioLinkForm, type LinkDraft,
} from "@/components/growth/bio/bioLinkForm";

const LINK: BioLink = {
  id: "l".repeat(15), link_id: "k".repeat(12), title: "OnlyFans", destination: "https://onlyfans.com/alice",
  icon: "onlyicon_abcdefghij.webp", icon_stock: "onlyicon", icon_url: "/admin/bio-pages/files/links/x/onlyicon.webp",
  background_image: "", background_url: "", is_adult: true, mode: "", tracking: false, default_tracking_code: "",
  geo: null, sort_order: 0, updated_at: "",
};
const run = (actions: Action[], from: BioLinkForm = INITIAL_LINK) => actions.reduce(bioLinkReducer, from);
const opened = (over: Partial<BioLink> = {}) => run([{ type: "open_edit", link: { ...LINK, ...over } }]);
const valid: LinkDraft = { ...draftOfLink(LINK) };

describe("bioLinkReducer open", () => {
  it("new → destination https://, disclosure closed", () => {
    const s = run([{ type: "open_new" }]);
    expect(s).toMatchObject({ open: true, base: null, advanced: false });
    expect(s.draft.destination).toBe("https://");
  });

  it.each<[string, Partial<BioLink>, boolean]>([
    ["with a code", { default_tracking_code: "123" }, true],
    ["with tracking on", { tracking: true }, true],
    ["with only a stored geo rule (no field for it)", { geo: { US: "5" } }, false],
    ["with none", {}, false],
  ])("edit %s → disclosure open %s", (_n, over, open) => {
    expect(opened(over).advanced).toBe(open);
  });

  it("a non-stock icon reads as current; a legacy mode as Profile default", () => {
    expect(opened({ icon: "mine.webp", icon_stock: null }).draft.icon).toBe("current");
    expect(opened({ icon: "", icon_stock: null }).draft.icon).toBe("none");
    expect(opened({ mode: "weird" }).draft.mode).toBe("");
  });
});

describe("linkFormError", () => {
  it.each([
    ["untouched legacy code", { title: "Updated" }, null],
    ["changed invalid code", { code: "2".repeat(20) }, CODE_MSG],
  ])("%s", (_name, patch, msg) => {
    const legacy = { ...LINK, default_tracking_code: "1".repeat(20) };
    const draft = { ...draftOfLink(legacy), ...patch };
    expect(linkFormError(draft, legacy)?.msg ?? null).toBe(msg);
    expect(canSubmit({ ...opened(legacy), draft })).toBe(msg === null);
  });
  it.each<[string, Partial<LinkDraft>, string | null, string[]]>([
    ["blank title", { title: "  " }, TITLE_MSG, ["title"]],
    ["https:// alone", { destination: " https:// " }, DEST_EMPTY_MSG, ["destination"]],
    ["ftp://x", { destination: "ftp://x" }, DEST_MSG, ["destination"]],
    ["a space", { destination: "https://a b" }, DEST_MSG, ["destination"]],
    ["a backslash", { destination: "/\\x" }, DEST_MSG, ["destination"]],
    ["//x", { destination: "//x" }, DEST_MSG, ["destination"]],
    ["HTTPS://x", { destination: "HTTPS://x" }, DEST_MSG, ["destination"]],
    ["/x path", { destination: "/x" }, null, []],
    ["http ok", { destination: "http://a.test/p?q=1" }, null, []],
    ["code 12a", { code: "12a" }, CODE_MSG, ["default_tracking_code"]],
    ["code 13 digits", { code: "1".repeat(13) }, CODE_MSG, ["default_tracking_code"]],
    ["code 12 digits", { code: "1".repeat(12) }, null, []],
  ])("%s", (_n, patch, msg, fields) => {
    const e = linkFormError({ ...valid, ...patch });
    expect(e?.msg ?? null).toBe(msg);
    expect(e?.fields ?? []).toEqual(fields);
  });
});

describe("buildLinkPayload", () => {
  it("create: the whole link, trimmed; none → icon null; never a geo key", () => {
    const d: LinkDraft = { ...run([{ type: "open_new" }]).draft, title: " T ", destination: " https://x.test " };
    expect(buildLinkPayload(null, d)).toEqual({
      title: "T", destination: "https://x.test", icon: null, is_adult: false, mode: "", tracking: false,
      default_tracking_code: "",
    });
    expect(buildLinkPayload(null, { ...d, icon: "igicon" })).not.toHaveProperty("geo");
  });

  it.each<[string, Partial<BioLink>, Partial<LinkDraft>, ReturnType<typeof buildLinkPayload>]>([
    ["unchanged edit", {}, {}, null],
    ["title only", {}, { title: " New " }, { title: "New" }],
    ["icon → none", {}, { icon: "none" }, { icon: null }],
    ["icon → stock", {}, { icon: "twitchicon" }, { icon: "twitchicon" }],
    ["current icon kept", { icon: "mine.webp", icon_stock: null }, { title: "X" }, { title: "X" }],
    ["stored geo rule left alone", { geo: { US: "5" } }, { title: "X" }, { title: "X" }],
    ["stored geo rule, nothing else changed", { geo: { US: "5" } }, {}, null],
    ["legacy code untouched", { default_tracking_code: "1".repeat(20) }, { title: "X" }, { title: "X" }],
  ])("%s", (_n, over, patch, want) => {
    const link = { ...LINK, ...over };
    expect(buildLinkPayload(link, { ...draftOfLink(link), ...patch })).toEqual(want);
  });
});

describe("bioLinkReducer submit", () => {
  it("a code refusal opens the disclosure", () => {
    const s = run([{ type: "set", patch: { code: "1a" } }, { type: "submit" }], opened());
    expect(s).toMatchObject({ busy: false, advanced: true, error: { msg: CODE_MSG, fields: ["default_tracking_code"] } });
  });

  it("an API refusal naming the code opens the disclosure", () => {
    const busy = run([{ type: "submit" }], opened());
    const s = run([{ type: "failed", msg: CODE_MSG, fields: ["default_tracking_code"] }], busy);
    expect(s).toMatchObject({ busy: false, advanced: true });
  });

  it("busy blocks a second submit", () => {
    const busy = run([{ type: "submit" }], opened());
    expect(busy.busy).toBe(true);
    expect(canSubmit(busy)).toBe(false);
    expect(run([{ type: "submit" }], busy)).toBe(busy);
  });

  it("saved after new → open edit with the base set, so a retry never creates twice", () => {
    const file = new File(["x"], "bg.png", { type: "image/png" });
    const busy = run([
      { type: "open_new" }, { type: "set", patch: { title: "T", destination: "https://x.test" } },
      { type: "pick_bg", file }, { type: "submit" },
    ]);
    const saved = run([{ type: "saved", link: { ...LINK, title: "T", destination: "https://x.test" } }], busy);
    expect(saved).toMatchObject({ open: true, base: { id: LINK.id }, bgFile: file });
    const failed = run([{ type: "failed", msg: "Link saved; the background failed: too big" }], saved);
    expect(failed.open).toBe(true);
    expect(buildLinkPayload(failed.open ? failed.base : null, failed.draft)).toBeNull();
  });

  it("a picked background clears Remove, and Remove clears the pick", () => {
    const file = new File(["x"], "bg.png");
    const s = run([{ type: "remove_bg", on: true }, { type: "pick_bg", file }], opened());
    expect(s).toMatchObject({ bgFile: file, bgRemove: false });
    expect(run([{ type: "remove_bg", on: true }], s)).toMatchObject({ bgFile: null, bgRemove: true });
  });

  it.each([
    ["clean", [], false],
    ["picked image", [{ type: "pick_bg", file: new File(["x"], "bg.png") }], true],
    ["remove image", [{ type: "remove_bg", on: true }], true],
    ["changed title", [{ type: "set", patch: { title: "Updated" } }], true],
  ] as const)("dirty: %s", (_name, actions, want) => {
    expect(isDirty(run([...actions], opened()))).toBe(want);
  });

  it("close resets", () => {
    expect(run([{ type: "close" }], opened())).toBe(INITIAL_LINK);
  });
});
