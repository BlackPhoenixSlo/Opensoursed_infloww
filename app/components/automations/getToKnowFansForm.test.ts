import { describe, expect, it } from "vitest";

import { unsaved } from "@/components/automations/sentDraft";
import type { AutomationKind } from "@/hooks/useAutomations";
import {
  buildPayload, gtkfReducer, initState, invalidReason, limitsOf, type GtkfAction, type GtkfDraft,
} from "./getToKnowFansForm";

const META: AutomationKind = {
  kind: "welcome_chatter_for_info", label: "Get to know fans", recurring: true, summary: "",
  knobs: [
    { key: "max_fan_messages", default: 10, min: 3, max: 100 },
    { key: "closing_ppv_price_cents", default: 1000, min: 300, max: 20_000 },
    { key: "closing_ppv_text", default: "one more for you" },
  ],
} as AutomationKind;
const LIM = limitsOf(META);

describe("initState", () => {
  it.each<[string, Record<string, unknown>, GtkfDraft]>([
    ["empty payload: the catalog defaults", {},
      { cutoff: "10", media: [], caption: "one more for you", price: "10" }],
    ["stored payload", { max_fan_messages: 7, closing_ppv_media_ids: [5, "6"], closing_ppv_text: "hi",
      closing_ppv_price_cents: 1250 },
    { cutoff: "7", media: [{ id: 5, type: "photo" }, { id: 6, type: "photo" }] as GtkfDraft["media"], caption: "hi",
      price: "12.5" }],
  ])("%s", (_name, p, want) => {
    expect(initState(p, META)).toEqual({ draft: want, sent: null });
  });
});

describe("buildPayload: the rule's payload with only the page's fields set", () => {
  it("round trips a stored payload and keeps the rest", () => {
    const p = { max_fan_messages: 7, closing_ppv_media_ids: [5], closing_ppv_text: "hi",
      closing_ppv_price_cents: 1250, every_other_knob: "x" };
    expect(buildPayload(initState(p, META).draft, p)).toEqual(p);
  });
  it("sends the typed values (cents)", () => {
    const d: GtkfDraft = { cutoff: "12", media: [], caption: "c", price: "4.99" };
    expect(buildPayload(d, { keep: 1 })).toEqual({
      keep: 1, max_fan_messages: 12, closing_ppv_media_ids: [], closing_ppv_text: "c", closing_ppv_price_cents: 499,
    });
  });
});

describe("invalidReason", () => {
  const ok: GtkfDraft = { cutoff: "10", media: [], caption: "", price: "10" };
  it.each<[string, Partial<GtkfDraft>, string | null]>([
    ["valid", {}, null],
    ["cutoff under min", { cutoff: "2" }, "Message cutoff: 3 to 100."],
    ["cutoff not an integer", { cutoff: "4.5" }, "Message cutoff: 3 to 100."],
    ["cutoff blank", { cutoff: "" }, "Message cutoff: 3 to 100."],
    ["price blank", { price: " " }, "Price: $3 to $200."],
    ["price over max", { price: "201" }, "Price: $3 to $200."],
    ["price at min", { price: "3" }, null],
  ])("%s", (_name, patch, want) => {
    expect(invalidReason({ ...ok, ...patch }, LIM)).toBe(want);
  });
});

describe("unsaved: 'Saved' only while nothing changed since the last Save sent", () => {
  const cutoff: GtkfAction = { type: "field", k: "cutoff", v: "12" };
  const caption: GtkfAction = { type: "field", k: "caption", v: "new" };
  const price: GtkfAction = { type: "field", k: "price", v: "15" };
  const media: GtkfAction = { type: "field", k: "media", v: [] };
  it.each<[string, GtkfAction[], boolean]>([
    ["no Save yet", [], true],
    ["Save", [{ type: "saved" }], false],
    ["edit then Save", [cutoff, { type: "saved" }], false],
    ["cutoff edited while the save is in flight", [{ type: "saved" }, cutoff], true],
    ["caption edited while the save is in flight", [{ type: "saved" }, caption], true],
    ["price edited while the save is in flight", [{ type: "saved" }, price], true],
    ["media changed while the save is in flight", [{ type: "saved" }, media], true],
    ["Save, an edit, Save again", [{ type: "saved" }, price, { type: "saved" }], false],
  ])("%s", (_name, actions, want) => {
    expect(unsaved(actions.reduce(gtkfReducer, initState({}, META)))).toBe(want);
  });
});
