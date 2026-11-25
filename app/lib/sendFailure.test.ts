import { describe, expect, it } from "vitest";

import { parseSendFailure } from "./sendFailure";

function relayBody(upstream: unknown) {
  return { detail: { upstream_status: 400, upstream_body: JSON.stringify(upstream) } };
}

const OF_400 = {
  error: {
    code: 0,
    message: "Something wrong with attached media, please try to upload it again",
    payload: { removeFromInputMediaIds: [3468787295] },
  },
  errors: {
    mediaFiles: ["Something wrong with attached media, please try to upload it again"],
  },
};

describe("parseSendFailure", () => {
  it("reads the reason AND the refused id from one wrapped 400", () => {
    expect(parseSendFailure(relayBody(OF_400))).toEqual({
      reason: "Something wrong with attached media, please try to upload it again",
      refusedMediaIds: [3468787295],
    });
  });

  it("keeps every id when OF names more than one", () => {
    const two = {
      ...OF_400,
      error: { ...OF_400.error, payload: { removeFromInputMediaIds: [3468787295, 3667292993] } },
    };
    expect(parseSendFailure(relayBody(two)).refusedMediaIds).toEqual([3468787295, 3667292993]);
  });

  it("still surfaces OF's sentence when it names no ids", () => {
    const bare = { error: { code: 0, message: "Cannot send message to this user" } };
    expect(parseSendFailure(relayBody(bare))).toEqual({
      reason: "Cannot send message to this user",
      refusedMediaIds: undefined,
    });
  });

  it("prefers the relay's OWN refusal — and marks the ids IT names", () => {
    const resale = {
      detail: {
        error: "owned_photos",
        message: "3 of 4 photos here are ones this fan already paid for. "
          + "A priced set needs at least 2 he has not seen.",
        owned_media: [4390218143, 3992451982, 4006142762],
      },
    };
    expect(parseSendFailure(resale)).toEqual({
      reason: resale.detail.message,
      refusedMediaIds: [4390218143, 3992451982, 4006142762],
    });
  });

  it("still answers with just the sentence when our block names no ids", () => {
    expect(parseSendFailure({ detail: { message: "already owned" } })).toEqual({
      reason: "already owned",
      refusedMediaIds: undefined,
    });
  });

  it("degrades to nothing rather than throwing on a truncated / non-json body", () => {
    expect(parseSendFailure({ detail: { upstream_body: '{"error":{"payl' } })).toEqual({});
    expect(parseSendFailure({ detail: { upstream_body: "<html>502</html>" } })).toEqual({});
    expect(parseSendFailure(undefined)).toEqual({});
    expect(parseSendFailure(null)).toEqual({});
  });

  it("drops junk entries instead of putting NaN on the bubble", () => {
    const junk = { error: { payload: { removeFromInputMediaIds: [3468787295, "nope", null, 0] } } };
    expect(parseSendFailure(relayBody(junk)).refusedMediaIds).toEqual([3468787295]);
  });
});

