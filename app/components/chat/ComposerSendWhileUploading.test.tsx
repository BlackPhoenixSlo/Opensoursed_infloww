/**
 * Send while a file still uploads (2026-10-16; sibling of
 * `ComposerUpload.test.tsx`). Send never waits on an upload: the Composer
 * clears at once, the message shows as a pending bubble with the file's blob
 * preview, and it goes out when its uploads land — from module state, so it
 * keeps going after the chat closes (MessagesPro keys ChatSurface by Fan, so a
 * chat switch unmounts the Composer and the send hook). An upload that fails
 * fails the bubble instead: nothing is sent without its file, and the bubble
 * offers Retry (upload again, then send) and discard.
 *
 * The chat is wired as ChatSurface wires it: the real `useChatMessages` (its
 * fetch disabled; the optimistic writers are what matter), the real
 * `useSendMessage`, `MessageList` and `Composer`. `relay.uploadFile` is the
 * harness mock, driven by hand; the Vault picker is the harness stub, whose
 * Confirm attaches FIXTURE_MEDIA (9102, 9101).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: null }) }));
// useChatMessages watches the SSE bus; jsdom has no EventSource.
vi.mock("@/lib/events", () => ({
  eventBus: { isConnected: () => false, onStateChange: () => () => {}, on: () => () => {} },
}));

// The harness first (see ComposerUpload.test.tsx).
import { observerStub, relayPost, resetComposerHarness, routeRelay } from "./composerTestHarness";
import { relay, type OFMessage, type VaultUploadResp } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";
import { useChatMessages } from "@/hooks/useChatMessages";
import { useSendMessage } from "@/hooks/useSendMessage";
import { clearSendStash } from "@/lib/sendStash";
import { SEND_GAP_MS } from "@/lib/sendGuards";
import { BubbleStatusRow } from "./BubbleMeta";
import { Composer, type ComposerApi } from "./Composer";
import type { PickedTemplate } from "./TemplatePicker";
import { MessageList } from "./MessageList";
import { baseProps, msg } from "./messageListTestHarness";

const ACCT = "acct-1";
const FAN = 42;
const ME = 555;
const uploadFile = vi.mocked(relay.uploadFile);

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const ok = (id: number): VaultUploadResp => ({ ready: true, deduped: false, vault_id: id, send_with: [id] });
const png = (name: string) => new File(["x"], name, { type: "image/png" });

// Uploads queue per Creator at module level, so one left hanging would hold
// every later case's; afterEach settles whatever a case left open.
const outstanding: Array<(e: unknown) => void> = [];

/** Each call to the upload gets its own deferred, in call order, with the
 *  AbortSignal the request was given. */
function queueUploads() {
  const pending: Array<ReturnType<typeof deferred<VaultUploadResp>> & { signal?: AbortSignal }> = [];
  uploadFile.mockImplementation((...args: unknown[]) => {
    const d = deferred<VaultUploadResp>();
    pending.push({ ...d, signal: args[4] as AbortSignal | undefined });
    outstanding.push(d.reject);
    return d.promise as Promise<any>;
  });
  return pending;
}

const api: { current: ComposerApi | null } = { current: null };

function Chat() {
  const handle = useChatMessages({ accountId: ACCT, fanId: FAN, enabled: false });
  const sender = useSendMessage({ accountId: ACCT, fanId: FAN, fromUserId: ME, fromUserName: "me", hookHandle: handle });
  return (
    <>
      <MessageList
        {...baseProps} accountId={ACCT} fanId={FAN} ownerUserId={ME} messages={handle.data ?? []}
        onRetry={sender.retry} onDiscard={sender.cancelOptimistic}
      />
      <Composer accountId={ACCT} fanId={FAN} composerApiRef={api} onSend={(a) => sender.send(a)} />
    </>
  );
}

let client: QueryClient;
// gcTime Infinity: the chat's cache must outlive the unmounted chat, as the
// app's does (its default gcTime is minutes, the test default is 0).
const renderChat = () => renderWithProviders(<Chat />, client);
const messages = () => client.getQueryData<OFMessage[]>(["messages", ACCT, FAN]) ?? [];
const sends = () => relayPost.mock.calls.filter((c) => String(c[0]) === `/api/of/v2/chats/${FAN}/messages`);
const fileInput = () => screen.getByLabelText("Upload from computer") as HTMLInputElement;
const sendButton = () => screen.getByRole("button", { name: "Send" });
const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts');
const flush = () => new Promise((r) => setTimeout(r, 0));
/** Moves the clock past the Composer's send-rate guard (only Date is faked;
 *  `afterEach` restores it), so a case can send its next message. */
const pastSendGap = () => {
  vi.useFakeTimers({ toFake: ["Date"], shouldAdvanceTime: true });
  vi.setSystemTime(Date.now() + SEND_GAP_MS);
};
const texts = () => messages().map((m) => m.text);
const cursor = () => JSON.parse(localStorage.getItem(`chatterly:scriptCursor:${ACCT}:${FAN}`) ?? "null");
const script = (scriptId: string, scriptStep: number, text: string): PickedTemplate => ({
  source: "local", text, displayText: text, mediaCount: 0, price: 0, lockedText: false,
  isWelcome: false, media: [], previews: [], taggedUsers: [], scriptId, scriptStep,
});
let serverId = 9000;

const createObjectURL = vi.fn((f: Blob) => `blob:${(f as File).name}`);
const revokeObjectURL = vi.fn();

beforeEach(() => {
  resetComposerHarness();
  // A bubble's media tiles lazy-load through an IntersectionObserver.
  vi.stubGlobal("IntersectionObserver", observerStub);
  uploadFile.mockReset();
  serverId = 9000;
  relayPost.mockImplementation((path: string, body?: unknown) =>
    Promise.resolve(path === `/api/of/v2/chats/${FAN}/messages` ? { id: ++serverId, media: [], text: (body as { text: string }).text } : {}));
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  createObjectURL.mockClear();
  revokeObjectURL.mockClear();
  Object.assign(URL, { createObjectURL, revokeObjectURL });
});
afterEach(async () => {
  cleanup();
  vi.useRealTimers();
  outstanding.splice(0).forEach((reject) => reject(new Error("test over")));
  await new Promise((r) => setTimeout(r, 0));
  relayPost.mockReset();
  relayPost.mockImplementation(() => Promise.resolve({}));
  vi.unstubAllGlobals();
  delete (URL as { createObjectURL?: unknown }).createObjectURL;
  delete (URL as { revokeObjectURL?: unknown }).revokeObjectURL;
});

describe("Send while a file uploads", () => {
  it("clears the Composer at once, shows a pending bubble with the preview, and sends when the upload lands, after the chat closed", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    const { unmount } = renderChat();

    await user.type(textbox(), "look");
    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    expect(sendButton()).toBeEnabled();
    await user.click(sendButton());

    expect(textbox()).toHaveValue("");
    expect(screen.queryByRole("group", { name: "Uploading a.png" })).not.toBeInTheDocument();
    expect(screen.getByText("uploading…")).toBeInTheDocument();
    const [bubble] = messages();
    expect(bubble).toMatchObject({ text: "look", _pending: true, _uploading: true });
    expect(bubble.media[0].files?.thumb?.url).toBe("blob:a.png");
    expect(sends()).toHaveLength(0);

    unmount();
    expect(revokeObjectURL).not.toHaveBeenCalledWith("blob:a.png");
    pending[0].resolve(ok(777));

    await waitFor(() => expect(sends()).toHaveLength(1));
    expect(sends()[0][1]).toMatchObject({ text: "look", media_files: [777], price: 0 });
    expect(sends()[0][2]).toMatchObject({ accountId: ACCT });
    await waitFor(() => expect(messages()[0]).toMatchObject({ id: 9001, _pending: false }));
  });

  it("a file-only message can be sent while its files upload; one that landed before Send rides before them", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    const { unmount } = renderChat();

    await user.upload(fileInput(), [png("a.png"), png("b.png")]);
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    pending[0].resolve(ok(1));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove attachment" })).toBeInTheDocument());
    await user.upload(fileInput(), png("c.png"));
    await user.click(sendButton());
    expect(messages()[0].media.map((m) => m.files?.thumb?.url)).toEqual(["blob:a.png", "blob:b.png", "blob:c.png"]);

    unmount();
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(2));
    pending[1].resolve(ok(2));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(3));
    expect(sends()).toHaveLength(0);
    pending[2].resolve(ok(3));

    await waitFor(() => expect(sends()).toHaveLength(1));
    expect(sends()[0][1]).toMatchObject({ text: "", media_files: [1, 2, 3] });
  });

  it("a Vault pick rides before the files still uploading, in the bubble and on the wire", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    renderChat();

    await user.click(screen.getByRole("button", { name: "Vault" }));
    await user.click(await screen.findByRole("button", { name: "Confirm fixture media" }));
    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    await user.click(sendButton());

    const placeholder = messages()[0].media[2];
    expect(messages()[0].media.map((m) => m.id).slice(0, 2)).toEqual([9102, 9101]);
    expect(placeholder.files?.thumb?.url).toBe("blob:a.png");
    pending[0].resolve(ok(1));
    await waitFor(() => expect(sends()).toHaveLength(1));
    expect(sends()[0][1]).toMatchObject({ media_files: [9102, 9101, 1] });
  });

  it("a failed upload fails the bubble and sends nothing; Retry, back in the chat, uploads again and sends", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    const first = renderChat();

    await user.type(textbox(), "pic");
    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    await user.click(sendButton());
    first.unmount();
    pending[0].reject(new Error('upstream 500: {"error":{"code":0,"message":"boom"}}'));
    await waitFor(() => expect(messages()[0]).toMatchObject({ _failed: true, _pending: false }));
    expect(messages()[0]._failedReason).toBe("Upload failed — OnlyFans error 500");
    await flush();
    expect(sends()).toHaveLength(0);

    renderChat();
    await user.click(screen.getByRole("button", { name: "failed — retry" }));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(2));
    expect((uploadFile.mock.calls[1][1] as File).name).toBe("a.png");
    expect(screen.getByText("uploading…")).toBeInTheDocument();
    pending[1].resolve(ok(42));

    await waitFor(() => expect(sends()).toHaveLength(1));
    expect(sends()[0][1]).toMatchObject({ text: "pic", media_files: [42] });
  });

  it("Retry uploads only the files that failed", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    renderChat();

    await user.upload(fileInput(), [png("a.png"), png("b.png")]);
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    await user.click(sendButton());
    pending[0].resolve(ok(1));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(2));
    pending[1].reject(new Error("upstream 502: bad gateway"));
    await screen.findByRole("button", { name: "failed — retry" });

    await user.click(screen.getByRole("button", { name: "failed — retry" }));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(3));
    expect((uploadFile.mock.calls[2][1] as File).name).toBe("b.png");
    pending[2].resolve(ok(2));
    await waitFor(() => expect(sends()).toHaveLength(1));
    expect(sends()[0][1]).toMatchObject({ media_files: [1, 2] });
  });

  it("discard removes a failed bubble, and nothing is sent", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    renderChat();

    await user.type(textbox(), "pic");
    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    await user.click(sendButton());
    pending[0].reject(new Error("upstream 500: boom"));
    await screen.findByRole("button", { name: "failed — retry" });

    await user.click(screen.getByRole("button", { name: "Discard message" }));
    expect(messages()).toHaveLength(0);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:a.png");
    await flush();
    expect(sends()).toHaveLength(0);
  });

  it("discarding a bubble still uploading aborts its running upload, never starts its queued one, and sends nothing", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    renderChat();

    await user.type(textbox(), "pic");
    await user.upload(fileInput(), [png("a.png"), png("b.png")]);
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    await user.click(sendButton());
    await user.click(screen.getByRole("button", { name: "Discard message" }));

    expect(messages()).toHaveLength(0);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:a.png");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:b.png");
    expect(pending[0].signal?.aborted).toBe(true);
    pending[0].resolve(ok(1));
    await flush();
    await flush();
    expect(uploadFile).toHaveBeenCalledTimes(1);
    expect(sends()).toHaveLength(0);
    expect(messages()).toHaveLength(0);
  });

  it("an identity switch (clearSendStash) stops a send's uploads as well as its send", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    renderChat();

    await user.upload(fileInput(), [png("a.png"), png("b.png")]);
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    await user.click(sendButton());
    clearSendStash();

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:a.png");
    expect(pending[0].signal?.aborted).toBe(true);
    await flush();
    await flush();
    expect(uploadFile).toHaveBeenCalledTimes(1);
    expect(sends()).toHaveLength(0);
  });

  it("discarding during Retry's re-upload aborts it", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    renderChat();

    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    await user.click(sendButton());
    pending[0].reject(new Error("upstream 500: boom"));
    await user.click(await screen.findByRole("button", { name: "failed — retry" }));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole("button", { name: "Discard message" }));

    expect(pending[1].signal?.aborted).toBe(true);
    pending[1].resolve(ok(1));
    await flush();
    expect(sends()).toHaveLength(0);
  });

  it("the chatter can type the next message right away and send it while the first still uploads", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    renderChat();

    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    await user.click(sendButton());
    expect(textbox()).toHaveFocus();
    pastSendGap();
    await user.keyboard("and this{Enter}");

    await waitFor(() => expect(sends()).toHaveLength(1));
    expect(sends()[0][1]).toMatchObject({ text: "and this", media_files: [] });
    expect(texts()).toEqual(["", "and this"]);
    pending[0].resolve(ok(5));
    await waitFor(() => expect(sends()).toHaveLength(2));
    expect(sends()[1][1]).toMatchObject({ media_files: [5] });
    // It went out second, so it moves below the message sent meanwhile.
    await waitFor(() => expect(messages().map((m) => m.id)).toEqual([9001, 9002]));
    expect(texts()).toEqual(["and this", ""]);
  });

  it("a Script picked for the next message while one uploads is not taken by the uploading one", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    renderChat();

    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    act(() => api.current!.applyTemplate(script("s1", 1, "step one")));
    await user.click(sendButton());
    expect(cursor()).toEqual({ scriptId: "s1", step: 1 });

    act(() => api.current!.applyTemplate(script("s2", 4, "other step")));
    pending[0].resolve(ok(7));
    await waitFor(() => expect(sends()).toHaveLength(1));
    await flush();
    expect(cursor()).toEqual({ scriptId: "s1", step: 1 });

    pastSendGap();
    await user.click(sendButton());
    await waitFor(() => expect(sends()).toHaveLength(2));
    expect(sends()[1][1]).toMatchObject({ text: "other step" });
    await waitFor(() => expect(cursor()).toEqual({ scriptId: "s2", step: 4 }));
  });

  it("a Script picked while a text send is still in flight is kept for the next message", async () => {
    const user = userEvent.setup();
    const post = deferred<unknown>();
    relayPost.mockImplementationOnce(() => post.promise);
    renderChat();

    act(() => api.current!.applyTemplate(script("s1", 1, "step one")));
    await user.click(sendButton());
    act(() => api.current!.applyTemplate(script("s2", 4, "other step")));
    post.resolve({ id: 9500, media: [], text: "step one" });
    await waitFor(() => expect(cursor()).toEqual({ scriptId: "s1", step: 1 }));
    await flush();
    expect(cursor()).toEqual({ scriptId: "s1", step: 1 });

    pastSendGap();
    await user.click(sendButton());
    await waitFor(() => expect(cursor()).toEqual({ scriptId: "s2", step: 4 }));
  });

  /** Upload a.png, pick two GIFs and Send; the upload is left running. */
  async function sendFileWithTwoGifs() {
    routeRelay("/giphy/proxy/gifs/trending", () => ({
      data: [1, 2].map((n) => ({
        type: "gif", id: `gif-synthetic-${n}`, title: `Synthetic ${n}`,
        images: { original: { url: `https://gif.test/${n}.gif` } },
      })),
      pagination: { total_count: 2, offset: 0 },
    }));
    const user = userEvent.setup();
    const pending = queueUploads();
    renderChat();

    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "GIF" }));
    await user.click(await screen.findByRole("button", { name: "Synthetic 1" }));
    await user.click(screen.getByRole("button", { name: "GIF" }));
    await user.click(await screen.findByRole("button", { name: "Synthetic 2" }));
    await user.click(sendButton());
    return { user, pending };
  }

  it("discarding a multi-GIF send still uploading drops its extra GIFs too", async () => {
    const { user } = await sendFileWithTwoGifs();
    await user.click(screen.getByRole("button", { name: "Discard message" }));
    await flush();
    await flush();
    expect(sends()).toHaveLength(0);
  });

  it("a multi-GIF send whose upload fails sends no extra GIFs (the chatter resends)", async () => {
    const { pending } = await sendFileWithTwoGifs();
    pending[0].reject(new Error("upstream 500: boom"));
    await waitFor(() => expect(messages()[0]).toMatchObject({ _failed: true }));
    await flush();
    await flush();
    expect(sends()).toHaveLength(0);
  });

  it("the extra GIFs of a send waiting on its files follow it, in pick order", async () => {
    const { pending } = await sendFileWithTwoGifs();

    // The Composer is free at once, but nothing goes out ahead of the file.
    expect(textbox()).toHaveValue("");
    await flush();
    expect(sends()).toHaveLength(0);
    pending[0].resolve(ok(3));
    await waitFor(() => expect(sends()).toHaveLength(2));
    expect(sends()[0][1]).toMatchObject({ giphy_id: "gif-synthetic-1", media_files: [3] });
    expect(sends()[1][1]).toMatchObject({ text: "", giphy_id: "gif-synthetic-2", media_files: [] });
  });
});

describe("BubbleStatusRow", () => {
  const noop = () => {};

  it("says uploading… (with discard) while the message waits on its files, sending… (without) otherwise", () => {
    const { rerender } = renderWithProviders(
      <BubbleStatusRow msg={msg({ id: -1, _tempId: -1, _pending: true, _uploading: true })}
                       side="right" scheduled={false} pending failed={false} onRetry={noop} onDiscard={noop} />,
    );
    expect(screen.getByText("uploading…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard message" })).toBeInTheDocument();
    rerender(
      <BubbleStatusRow msg={msg({ id: -1, _tempId: -1, _pending: true })}
                       side="right" scheduled={false} pending failed={false} onRetry={noop} onDiscard={noop} />,
    );
    expect(screen.getByText("sending…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard message" })).not.toBeInTheDocument();
  });

  it("offers discard on a failed bubble only when the list can discard", () => {
    const onDiscard = vi.fn();
    const failed = msg({ id: -2, _tempId: -2, _failed: true, _failedReason: "Upload failed — OnlyFans error 500" });
    const { rerender } = renderWithProviders(
      <BubbleStatusRow msg={failed} side="right" scheduled={false} pending={false} failed onRetry={noop} />,
    );
    expect(screen.queryByRole("button", { name: "Discard message" })).not.toBeInTheDocument();
    rerender(
      <BubbleStatusRow msg={failed} side="right" scheduled={false} pending={false} failed onRetry={noop} onDiscard={onDiscard} />,
    );
    within(screen.getByText(/OnlyFans error 500/).parentElement!).getByRole("button", { name: "Discard message" }).click();
    expect(onDiscard).toHaveBeenCalledWith(-2);
  });
});
