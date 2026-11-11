import { describe, expect, it } from "vitest";

import { PAYLOAD_RAW, withoutDryRun } from "./rulePayload";

describe("PAYLOAD_RAW", () => {
  it.each<[string, string, Record<string, unknown>]>([
    ["blank text is {}", "  ", {}],
    ["an object passes through", '{"messages":[{"text":"a"}],"resend_count":2}', { messages: [{ text: "a" }], resend_count: 2 }],
  ])("parses: %s", (_name, text, want) => {
    expect(PAYLOAD_RAW.parse(text)).toEqual(want);
  });

  it.each<[string, string, string]>([
    ["not JSON", "{", "Payload is not valid JSON"],
    ["an array", "[1]", "Payload must be a JSON object"],
    ["null", "null", "Payload must be a JSON object"],
    ["a string", '"x"', "Payload must be a JSON object"],
    // The switch owns dry_run: a typed one would be dropped and the rule saved live.
    ["a typed dry_run", '{"posts":[],"dry_run":true}', 'Remove "dry_run" here'],
    ["a typed dry_run false", '{"posts":[],"dry_run":false}', 'Remove "dry_run" here'],
  ])("rejects %s", (_name, text, error) => {
    expect(() => PAYLOAD_RAW.parse(text)).toThrow(error);
  });

  it("withoutDryRun copies, leaving the input intact", () => {
    const p = { posts: [1], dry_run: true };
    expect(withoutDryRun(p)).toEqual({ posts: [1] });
    expect(p.dry_run).toBe(true);
    expect(withoutDryRun(undefined)).toEqual({});
  });
});
