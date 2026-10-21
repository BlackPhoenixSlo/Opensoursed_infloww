/**
 * useUnsendChoice — the Thread's unsend prompt (roadmap 4.15d,
 * 04-messages-pro.md P3). A mass-sent bubble asks the scope up front, "Unsend
 * from this conversation" preselected; other bubbles keep the one confirm and
 * the follow-up when OF's reply names a live queue. The unsender is a fake:
 * the calls it records are the ones `useUnsendMessage` would send.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { OFMessage } from "@/lib/relay";
import { useUnsendChoice } from "./UnsendChoice";

/** Function permissions the role denies (`useActionAllowed`); none unless a case adds one. */
const denied = vi.hoisted(() => new Set<string>());
vi.mock("@/components/shell/useGrantedPages", () => ({ useActionAllowed: (action: string) => !denied.has(action) }));

const QUEUE = { id: 48776990679, sentCount: 12, viewedCount: 3, canUnsend: true, isCanceled: false };
const MASS = { id: 11706310608197, text: "fixture mass", isFromQueue: true, canUnsendQueue: true } as unknown as OFMessage;
const DIRECT = { id: 11700529168223, text: "fixture direct", isFromQueue: false } as unknown as OFMessage;

const unsendOne = vi.fn();
const unsendQueue = vi.fn();
let confirm: MockInstance<typeof window.confirm>;
let alert: MockInstance<typeof window.alert>;

function Harness({ msg }: { msg: OFMessage }) {
  const unsend = useUnsendChoice({ unsendOne, unsendQueue });
  const onUnsend = unsend.onUnsend;
  return (
    <>
      {onUnsend && <button type="button" onClick={() => onUnsend(msg)}>Unsend bubble</button>}
      {unsend.dialog}
    </>
  );
}

beforeEach(() => {
  unsendOne.mockReset().mockResolvedValue({ success: true, queue: QUEUE });
  unsendQueue.mockReset().mockResolvedValue(undefined);
  confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  alert = vi.spyOn(window, "alert").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  denied.clear();
  confirm.mockRestore();
  alert.mockRestore();
});

describe("useUnsendChoice", () => {
  it('a mass-sent bubble asks with two options, "Unsend from this conversation" preselected; Unsend then sends the per-chat DELETE only, with no confirm', async () => {
    const user = userEvent.setup();
    render(<Harness msg={MASS} />);
    await user.click(screen.getByRole("button", { name: "Unsend bubble" }));
    const dialog = screen.getByRole("dialog", { name: "Unsend message" });
    expect(screen.getByRole("radio", { name: "Unsend from this conversation" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Unsend for all recipients" })).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Unsend" }));
    await waitFor(() => expect(unsendOne).toHaveBeenCalledWith(MASS));
    expect(dialog).not.toBeInTheDocument();
    expect(unsendQueue).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
  });

  it('"Unsend for all recipients" sends the per-chat DELETE, then the queue OF echoes, with no second prompt', async () => {
    const user = userEvent.setup();
    render(<Harness msg={MASS} />);
    await user.click(screen.getByRole("button", { name: "Unsend bubble" }));
    await user.click(screen.getByRole("radio", { name: "Unsend for all recipients" }));
    await user.click(screen.getByRole("button", { name: "Unsend" }));
    await waitFor(() => expect(unsendQueue).toHaveBeenCalledWith(QUEUE.id));
    expect(unsendOne).toHaveBeenCalledWith(MASS);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("for all recipients, a queue OF no longer lets go stays: the alert says it was unsent from this conversation only", async () => {
    const user = userEvent.setup();
    unsendOne.mockResolvedValue({ queue: { ...QUEUE, canUnsend: false } });
    render(<Harness msg={MASS} />);
    await user.click(screen.getByRole("button", { name: "Unsend bubble" }));
    await user.click(screen.getByRole("radio", { name: "Unsend for all recipients" }));
    await user.click(screen.getByRole("button", { name: "Unsend" }));
    await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringMatching(/^Unsent from this conversation only/)));
    expect(unsendQueue).not.toHaveBeenCalled();
  });

  it("Cancel and Escape close the dialog and send nothing", async () => {
    const user = userEvent.setup();
    render(<Harness msg={MASS} />);
    await user.click(screen.getByRole("button", { name: "Unsend bubble" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Unsend bubble" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(unsendOne).not.toHaveBeenCalled();
  });

  it("any other bubble keeps the one confirm; when OF's reply names a live queue, the follow-up asks once per queue", async () => {
    const user = userEvent.setup();
    render(<Harness msg={DIRECT} />);
    await user.click(screen.getByRole("button", { name: "Unsend bubble" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(unsendQueue).toHaveBeenCalledWith(QUEUE.id));
    expect(confirm.mock.calls.map((c) => c[0])).toEqual([
      "Unsend this message from this chat? OF allows this within ~24h.",
      "This message was part of a mass send. Sent to 12 fans, 3 viewed. Also unsend it for all recipients?",
    ]);
    await user.click(screen.getByRole("button", { name: "Unsend bubble" }));
    await waitFor(() => expect(unsendOne).toHaveBeenCalledTimes(2));
    expect(confirm).toHaveBeenCalledTimes(3);
    expect(unsendQueue).toHaveBeenCalledTimes(1);

    confirm.mockReturnValue(false);
    await user.click(screen.getByRole("button", { name: "Unsend bubble" }));
    expect(unsendOne).toHaveBeenCalledTimes(2);
  });

  it("a role denied Unsend gets no unsend at all", () => {
    denied.add("unsend");
    render(<Harness msg={DIRECT} />);
    expect(screen.queryByRole("button", { name: "Unsend bubble" })).toBeNull();
  });

  it("a role denied mass messages unsends a mass-sent bubble from this chat only, with no scope dialog or follow-up", async () => {
    const user = userEvent.setup();
    denied.add("mass-message");
    render(<Harness msg={MASS} />);
    await user.click(screen.getByRole("button", { name: "Unsend bubble" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(unsendOne).toHaveBeenCalledWith(MASS));
    expect(confirm.mock.calls.map((c) => c[0])).toEqual(["Unsend this message from this chat? OF allows this within ~24h."]);
    expect(unsendQueue).not.toHaveBeenCalled();
  });
});
