/** The bell's quick reply on the real send outcome: only a send that went out reads "Sent"; a failed one keeps its
 *  bubble (flagged, with Retry) and the line; a throw never leaves the field stuck; the bubble is ours. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const send = vi.fn();
const retry = vi.fn();
const cancelOptimistic = vi.fn();
const sendOpts = vi.fn();
// The Fan's thread cache as the bell reads it (the Thread's Retry writes the same rows).
const thread: { data?: Array<{ id: number; _tempId?: number; _pending?: boolean }> } = {};
vi.mock("@/hooks/useChatMessages", () => ({ useChatMessages: () => thread }));
vi.mock("@/hooks/useSendMessage", () => ({
  useSendMessage: (o: unknown) => { sendOpts(o); return { send, cancelOptimistic, retry, inflight: 0 }; },
}));
vi.mock("@/lib/relay", () => ({ relay: { get: async () => ({ id: 77, name: "Ava" }) } }));

import { QuickReplyField } from "@/components/NotificationQuickReply";
import { clearSendStash, sendStash } from "@/lib/sendStash";

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={qc}><QuickReplyField accountId="a1" fanId={5} name="Bob" /></QueryClientProvider>);
}
const field = () => screen.getByLabelText("Reply to Bob") as HTMLInputElement;
const reply = (text: string) => {
  fireEvent.change(field(), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
};

afterEach(() => {
  cleanup();
  send.mockReset();
  retry.mockReset();
  cancelOptimistic.mockReset();
  clearSendStash();
  sendOpts.mockReset();
  delete thread.data;
});

describe("QuickReplyField", () => {
  it("sent: Sent, line cleared", async () => {
    send.mockResolvedValue({ tempId: -1, failure: null, settled: Promise.resolve({ sent: true }) });
    mount();
    reply(" hi ");
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Sent"));
    expect(send).toHaveBeenCalledWith({ text: "hi" });
    expect(field().value).toBe("");
  });

  it("failed: the reason, line kept, failed bubble kept (no cancel)", async () => {
    const failure = { reason: "Fan blocked you" };
    send.mockResolvedValue({ tempId: -1, failure, settled: Promise.resolve({ sent: false, failure }) });
    mount();
    reply("hi");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Fan blocked you"));
    expect(cancelOptimistic).not.toHaveBeenCalled();
    expect(field().value).toBe("hi");
  });

  // The failed bubble stays stashed (the real send leaves it for Retry); the mock stands in for that.
  const failOnce = (text: string) => {
    const failure = { reason: "Fan blocked you" };
    send.mockImplementationOnce(async () => {
      sendStash.set(-1, { input: { text }, files: [] });
      return { tempId: -1, failure, settled: Promise.resolve({ sent: false, failure }) };
    });
  };

  it("fail, resend: one bubble, one send", async () => {
    failOnce("hi");
    retry.mockResolvedValue({ sent: true });
    mount();
    reply("hi");
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Sent"));
    expect(send).toHaveBeenCalledTimes(1);
    expect(retry).toHaveBeenCalledWith(-1);
    expect(cancelOptimistic).not.toHaveBeenCalled();
  });

  it("fail, then another line: the failed bubble is dropped, the new line sent", async () => {
    failOnce("hi");
    send.mockResolvedValueOnce({ tempId: -2, failure: null, settled: Promise.resolve({ sent: true }) });
    mount();
    reply("hi");
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    reply("hello");
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Sent"));
    expect(cancelOptimistic).toHaveBeenCalledWith(-1);
    expect(send).toHaveBeenCalledTimes(2);
    expect(send).toHaveBeenLastCalledWith({ text: "hello" });
    expect(retry).not.toHaveBeenCalled();
  });

  it("fail, Thread Retry in flight, bell Send: no second send", async () => {
    failOnce("hi");
    mount();
    reply("hi");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Fan blocked you"));
    thread.data = [{ id: -1, _tempId: -1, _pending: true }];
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Already sending from the chat."));
    expect(send).toHaveBeenCalledTimes(1);
    expect(retry).not.toHaveBeenCalled();
    expect(field().value).toBe("hi");
  });

  it("fail, Thread Retry sent it, bell Send same line: no send, field cleared, not Sent", async () => {
    failOnce("hi");
    mount();
    reply("hi");
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    sendStash.sent(-1);
    thread.data = [{ id: 901, _tempId: -1 }];
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(field().value).toBe(""));
    expect(send).toHaveBeenCalledTimes(1);
    expect(retry).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("fail, Thread Discard, bell Send same line: exactly one send", async () => {
    failOnce("hi");
    send.mockResolvedValueOnce({ tempId: -2, failure: null, settled: Promise.resolve({ sent: true }) });
    mount();
    reply("hi");
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    sendStash.discard(-1);
    thread.data = [];
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Sent"));
    expect(send).toHaveBeenCalledTimes(2);
    expect(send).toHaveBeenLastCalledWith({ text: "hi" });
    expect(retry).not.toHaveBeenCalled();
  });

  it("discarded mid-way (sent false, no failure) is not Sent", async () => {
    send.mockResolvedValue({ tempId: -1, failure: null, settled: Promise.resolve({ sent: false }) });
    mount();
    reply("hi");
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("a throw frees the field", async () => {
    send.mockRejectedValue(new Error("offline"));
    mount();
    reply("hi");
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("offline"));
    expect(field().disabled).toBe(false);
  });

  it("sends as the Creator (the bubble sits on our side)", async () => {
    mount();
    await waitFor(() => expect(sendOpts).toHaveBeenLastCalledWith(expect.objectContaining({ fromUserId: 77, fromUserName: "Ava" })));
  });
});
