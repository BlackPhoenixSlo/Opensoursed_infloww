import { describe, expect, it } from "vitest";

import {
  autoUnsendReducer, buildPayload, canSave, initialAutoUnsendForm, saveBody, type AutoUnsendAction, type AutoUnsendForm,
} from "./autoUnsendForm";

const run = (actions: AutoUnsendAction[], from: AutoUnsendForm = initialAutoUnsendForm) => actions.reduce(autoUnsendReducer, from);
const hydrate = (isEnabled: boolean, policy: Record<string, number>): AutoUnsendAction => ({ type: "hydrate", isEnabled, policy });

describe("autoUnsendReducer", () => {
  it.each<[string, AutoUnsendAction[], Partial<AutoUnsendForm>]>([
    ["defaults: off, free text on at 4 h, image 24 h and PPV 48 h off", [],
      { enabled: false, text: { on: true, h: 4 }, img: { on: false, h: 24 }, price: { on: false, h: 48 }, hydrated: false }],
    ["hydrate takes the saved rule's on/off and hours; a class it lacks is off at its default",
      [hydrate(true, { mass_media_hours: 6, mass_price_hours: 72 })],
      { enabled: true, text: { on: false, h: 4 }, img: { on: true, h: 6 }, price: { on: true, h: 72 }, hydrated: true }],
    ["hydrate of an empty policy: every class off at its default hours", [hydrate(false, {})],
      { enabled: false, text: { on: false, h: 4 }, img: { on: false, h: 24 }, price: { on: false, h: 48 }, hydrated: true }],
    ["hydrate runs once: a later load leaves the edits alone",
      [hydrate(false, { mass_text_hours: 2 }), { type: "classOn", cls: "img", on: true }, hydrate(true, { mass_price_hours: 9 })],
      { enabled: false, text: { on: true, h: 2 }, img: { on: true, h: 24 }, price: { on: false, h: 48 } }],
    ["enabled toggles only the rule", [{ type: "enabled", on: true }],
      { enabled: true, text: { on: true, h: 4 } }],
    ["a class toggle keeps its hours", [{ type: "hours", cls: "price", hours: 12 }, { type: "classOn", cls: "price", on: true }],
      { price: { on: true, h: 12 } }],
    ["hours: numeric input updates the selected class", [{ type: "hours", cls: "img", hours: 7 }],
      { text: { on: true, h: 4 }, img: { on: false, h: 7 }, price: { on: false, h: 48 } }],
    ["hours: zero is clamped to 1", [{ type: "hours", cls: "text", hours: 0 }], { text: { on: true, h: 1 } }],
  ])("%s", (_name, actions, want) => {
    expect(run(actions)).toMatchObject(want);
  });
});

describe("canSave + buildPayload (the rule's payload, pinned)", () => {
  it.each<[string, AutoUnsendAction[], boolean, { policy: Record<string, number> }]>([
    ["default: free text only", [], true, { policy: { mass_text_hours: 4 } }],
    ["all three on", [{ type: "classOn", cls: "img", on: true }, { type: "classOn", cls: "price", on: true }], true,
      { policy: { mass_text_hours: 4, mass_media_hours: 24, mass_price_hours: 48 } }],
    ["an off class is left out even with hours typed", [{ type: "hours", cls: "img", hours: 3 }], true,
      { policy: { mass_text_hours: 4 } }],
    ["the saved rule round-trips", [hydrate(true, { mass_media_hours: 6, mass_price_hours: 72 })], true,
      { policy: { mass_media_hours: 6, mass_price_hours: 72 } }],
    ["no class on: Save is off (the payload would be the per-chat sweep)", [{ type: "classOn", cls: "text", on: false }],
      false, { policy: {} }],
    ["enabled is not part of the payload", [{ type: "enabled", on: true }], true, { policy: { mass_text_hours: 4 } }],
  ])("%s", (_name, actions, save, payload) => {
    const s = run(actions);
    expect(canSave(s)).toBe(save);
    expect(buildPayload(s)).toEqual(payload);
  });
});

describe("saveBody", () => {
  const off = [{ type: "classOn", cls: "text", on: false }] as AutoUnsendAction[];
  it.each<[string, AutoUnsendAction[], boolean, ReturnType<typeof saveBody>]>([
    ["a class on: on/off plus the payload", [{ type: "enabled", on: true }], false,
      { is_enabled: true, payload: { policy: { mass_text_hours: 4 } } }],
    ["no class, rule on: nothing sent", [...off, { type: "enabled", on: true }], true, null],
    ["no class, no rule yet, off: nothing sent", off, false, null],
    ["no class, saved rule turned off: only is_enabled, the saved policy stays", [hydrate(true, {}), { type: "enabled", on: false }], true,
      { is_enabled: false }],
  ])("%s", (_name, actions, hasRule, want) => {
    expect(saveBody(run(actions), hasRule)).toEqual(want);
  });
});
