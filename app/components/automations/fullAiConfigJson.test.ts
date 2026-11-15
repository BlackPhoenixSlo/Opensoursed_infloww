import { describe, expect, it } from "vitest";

import type { ConfigBody, FullAiConfig } from "./fullAiConfig";
import { jsonEditInit, jsonEditReducer, jsonMoved, jsonTyped, prettyJson } from "./fullAiConfigJson";
import { initTestChat, testChatReducer, type TestChatAction, type TestChatState } from "./fullAiTestChat";

const run = (s: TestChatState, ...actions: TestChatAction[]) => actions.reduce(testChatReducer, s);
const CP = { version: 1, reply_speed: "0-2m", text_style: "girl", gifs: false, writers: ["euryale-v2.3"] };
const body = (over: Partial<ConfigBody> = {}): ConfigBody =>
  ({ checkpoint: CP, previous: null, draft: CP, rev: 3, errors: [],
    limits: { max_writers: 6, reply_speeds: ["0-2m", "0-15-60"], default_reply_speed: "0-2m",
      info_questions: ["pick", "list"], caption_writers: ["chat", "caption"] }, ...over });
const slower = { ...CP, reply_speed: "0-15-60" };
const external = (draft: FullAiConfig = slower, rev = 4): TestChatAction => ({ type: "externalDraft", body: body({ draft, rev }) });
/** Loaded at rev 3 with a Fan line typed. */
const ready = () => run(initTestChat("p1"), { type: "loaded", body: body() }, { type: "edit", text: "hey" });
/** An unsaved edit the server refused: still dirty, nothing out. */
const unsaved = () => run(ready(), { type: "editDraft", draft: { ...CP, gifs: true } }, { type: "saveDraft" },
  { type: "configFailed", errors: ["gifs: bad"] });

describe("JSON modal boxes: stored on the rev they were read at (rwl-c F1)", () => {
  it("jsonEditInit reads both sides and the rev; typing marks typed, typing it back clears it", () => {
    const ed = jsonEditInit(run(ready(), external()));
    expect(ed).toEqual({ baseRev: 4, opened: { checkpoint: prettyJson(CP), draft: prettyJson(slower) },
      text: { checkpoint: prettyJson(CP), draft: prettyJson(slower) } });
    const t = jsonEditReducer(ed, { type: "type", side: "draft", text: "{}" });
    expect([jsonTyped(ed), jsonTyped(t), t.text.checkpoint, t.baseRev]).toEqual([false, true, prettyJson(CP), 4]);
    expect(jsonTyped(jsonEditReducer(t, { type: "type", side: "draft", text: prettyJson(slower) }))).toBe(false);
  });
  it.each<[string, TestChatAction[], boolean]>([
    ["nothing moved", [], false],
    ["an Apply adopted underneath", [external()], true],
    ["an equal rev refetched", [external(slower, 3)], false],
  ])("jsonMoved: %s → %s; the boxes stay as opened", (_n, actions, want) => {
    const s0 = ready();
    const ed = jsonEditInit(s0);
    const s = run(s0, ...actions);
    expect([jsonMoved(ed, s), jsonTyped(ed), ed.baseRev]).toEqual([want, false, 3]);
  });
  it("jsonMoved: an Apply waiting as a conflict (the page's rev unchanged) counts as moved", () => {
    const s0 = unsaved();
    const s = run(s0, external());
    expect([s.rev, jsonMoved(jsonEditInit(s0), s)]).toEqual([3, true]);
  });
});
