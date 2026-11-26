import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { failMsg } from "@/lib/threadCache";
import type { OFMessage } from "@/lib/relay";
import { parseSendFailure } from "@/lib/sendFailure";

import { BubbleStatusRow } from "./BubbleMeta";

afterEach(cleanup);

const failed = (body: unknown): OFMessage =>
  failMsg([{ id: -1, _tempId: -1, _pending: true, text: "hi" } as OFMessage], -1, parseSendFailure(body))[0];

const row = (msg: OFMessage) =>
  render(<BubbleStatusRow msg={msg} side="right" scheduled={false} pending={false} failed onRetry={() => {}} />);

describe("BubbleStatusRow failed send", () => {
  it("writes_paused shows Sending paused and no Retry", () => {
    row(failed({ detail: { error: "writes_paused" } }));
    expect(screen.getByText("Sending paused")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /retry/ })).toBeNull();
  });

  it("an ordinary refusal keeps failed — retry", () => {
    row(failed({ detail: { message: "Cannot send message to this user" } }));
    expect(screen.getByRole("button", { name: /retry/ })).toBeTruthy();
    expect(screen.queryByText("Sending paused")).toBeNull();
  });
});
