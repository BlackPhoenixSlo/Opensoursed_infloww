/**
 * Composer upload from the computer (seam 1: the `Composer`, through
 * `composerTestHarness`; sibling of `ComposerToolbar.test.tsx`). Restored
 * 2026-10-16 at the human's request (docs/spec/phase-04-composer-ppv-vault.md,
 * Out of Scope note): row 3's Upload, a drop on the Composer and a pasted
 * image each upload through `POST /api/of/v2/upload`; every file shows a
 * chip until it lands, then rides on the send exactly as a Vault pick does.
 * `relay.uploadFile` is the harness mock; every case drives it by hand. The
 * Vault picker is a local stub that records the ids it was opened with and
 * confirms whatever a case sets in `picker.confirm`. jsdom has no blob URLs,
 * so `URL.createObjectURL` / `revokeObjectURL` are stubbed per case.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
const picker = vi.hoisted(() => ({ initialSelectedIds: [] as number[], confirm: [] as unknown[] }));
vi.mock("./VaultPicker", () => ({
  VaultPicker: ({ initialSelectedIds, onConfirm, onClose }: {
    initialSelectedIds: number[]; onConfirm: (m: VaultMedia[]) => void; onClose: () => void;
  }) => {
    picker.initialSelectedIds = initialSelectedIds;
    return (
      <div role="dialog" aria-label="Vault picker stub">
        <button type="button" onClick={() => { onConfirm(picker.confirm as VaultMedia[]); onClose(); }}>Confirm</button>
      </div>
    );
  },
}));

// The harness first: importing `@/lib/relay` first runs the mock factory while
// the harness is mid-import, and the hook then gets the real relay.
import { pickSendAt, renderComposer, resetComposerHarness } from "./composerTestHarness";
import { relay, type VaultMedia, type VaultUploadResp } from "@/lib/relay";

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

/** Each call to the upload gets its own deferred, in call order. */
function queueUploads() {
  const pending: Array<ReturnType<typeof deferred<VaultUploadResp>>> = [];
  uploadFile.mockImplementation(() => {
    const d = deferred<VaultUploadResp>();
    pending.push(d);
    outstanding.push(d.reject);
    return d.promise as Promise<any>;
  });
  return pending;
}

const fileInput = () => screen.getByLabelText("Upload from computer") as HTMLInputElement;
const sendButton = () => screen.getByRole("button", { name: "Send" });
const textbox = () => screen.getByPlaceholderText('Press "/" + keyword to quickly search scripts');

const createObjectURL = vi.fn((f: Blob) => `blob:${(f as File).name}`);
const revokeObjectURL = vi.fn();

beforeEach(() => {
  resetComposerHarness();
  uploadFile.mockReset();
  createObjectURL.mockClear();
  revokeObjectURL.mockClear();
  Object.assign(URL, { createObjectURL, revokeObjectURL });
  picker.initialSelectedIds = [];
  picker.confirm = [];
});
afterEach(async () => {
  cleanup();
  outstanding.splice(0).forEach((reject) => reject(new Error("test over")));
  await new Promise((r) => setTimeout(r, 0));
  delete (URL as { createObjectURL?: unknown }).createObjectURL;
  delete (URL as { revokeObjectURL?: unknown }).revokeObjectURL;
});

describe("Composer: upload from computer", () => {
  it("choosing two files shows two uploading chips and uploads each file once", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    await renderComposer();

    await user.upload(fileInput(), [png("a.png"), png("b.png")]);

    expect(screen.getByRole("group", { name: "Uploading a.png" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Uploading b.png" })).toBeInTheDocument();
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    pending[0].resolve(ok(501));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(2));
    pending[1].resolve(ok(502));
    await waitFor(() => expect(screen.queryByRole("group", { name: /^Uploading/ })).not.toBeInTheDocument());

    expect(uploadFile.mock.calls.map((c) => [c[0], (c[1] as File).name, c[2], c[3]])).toEqual([
      ["/api/of/v2/upload", "a.png", "file", { accountId: "acct-1" }],
      ["/api/of/v2/upload", "b.png", "file", { accountId: "acct-1" }],
    ]);
  });

  it("a finished upload becomes an attachment and the sent message carries its media id", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    const { onSend } = await renderComposer();

    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    pending[0].resolve(ok(777));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove attachment" })).toBeInTheDocument());

    await user.click(sendButton());
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend.mock.calls[0][0].attached?.map((m) => m.id)).toEqual([777]);
  });

  it("a fresh claim rides as its claim, as a Vault pick of a transcoding item would", async () => {
    const user = userEvent.setup();
    const claim = { processId: "p1", host: "h", name: "n", extra: "e" };
    uploadFile.mockResolvedValue({ ready: true, deduped: false, vault_id: null, send_with: [claim] });
    const { onSend } = await renderComposer();

    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove attachment" })).toBeInTheDocument());
    await user.click(sendButton());

    expect(onSend.mock.calls[0][0].attached?.map((m) => m._claim)).toEqual([claim]);
  });

  it("Send and Enter stay free while a file uploads and hand the upload to the send; the Composer clears at once", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    const { onSend } = await renderComposer();

    await user.type(textbox(), "hi");
    await user.upload(fileInput(), png("a.png"));

    expect(sendButton()).toBeEnabled();
    expect(sendButton()).toHaveAttribute("title", "Enter to send · Shift+Enter for newline");
    await user.type(textbox(), "{Enter}");

    expect(onSend).toHaveBeenCalledTimes(1);
    const args = onSend.mock.calls[0][0];
    expect(args.text).toBe("hi");
    expect(args.attached).toBeUndefined();
    expect(args.uploads?.map((u) => [u.file.name, u.previewUrl])).toEqual([["a.png", "blob:a.png"]]);
    expect(textbox()).toHaveValue("");
    expect(screen.queryByRole("group", { name: "Uploading a.png" })).not.toBeInTheDocument();
    // The send owns the upload now: it lands as the send's media, not as a tile.
    pending[0].resolve(ok(9));
    await expect(args.uploads![0].done).resolves.toMatchObject([{ id: 9, _localPreview: "blob:a.png" }]);
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole("button", { name: "Remove attachment" })).not.toBeInTheDocument();
    expect(revokeObjectURL).not.toHaveBeenCalledWith("blob:a.png");
  });

  it("Schedule and the Timed message wait for a running upload, as scheduling needs its media ids", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    const { onSend } = await renderComposer();
    const wait = "Wait for the upload to finish before scheduling";

    await user.type(textbox(), "hi");
    await user.upload(fileInput(), png("a.png"));
    await user.click(screen.getByRole("button", { name: "Timed message" }));
    const timed = within(screen.getByRole("region", { name: "Timed message" }));
    await user.type(timed.getByRole("textbox", { name: "Minutes" }), "5");
    expect(timed.getByRole("button", { name: "Start" })).toBeDisabled();
    expect(timed.getByRole("button", { name: "Start" })).toHaveAttribute("title", wait);
    await user.click(screen.getByRole("button", { name: "Timed message" }));
    await pickSendAt(user, 15);
    expect(screen.getByRole("button", { name: "Schedule", description: wait })).toBeDisabled();
    await user.type(textbox(), "{Enter}");
    expect(onSend).not.toHaveBeenCalled();

    pending[0]?.resolve(ok(9));
    await waitFor(() => expect(screen.getByRole("button", {
      name: "Schedule", description: "Enter to send · Shift+Enter for newline",
    })).toBeEnabled());
  });

  it("a failed upload shows the error and Retry, and Retry uploads the file again", async () => {
    const user = userEvent.setup();
    const raw = 'upstream 500: {"error":{"code":0,"message":"boom"}}';
    uploadFile.mockRejectedValueOnce(new Error(raw));
    uploadFile.mockResolvedValueOnce(ok(42));
    const { onSend } = await renderComposer();

    await user.upload(fileInput(), png("a.png"));
    const failed = await screen.findByRole("group", { name: "Upload failed: a.png" });
    expect(within(failed).getByText("⚠ Upload failed — OnlyFans error 500")).toBeInTheDocument();
    expect(failed).toHaveAttribute("title", `a.png: ${raw}`);

    await user.click(within(failed).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(2));
    expect((uploadFile.mock.calls[1][1] as File).name).toBe("a.png");
    await waitFor(() => expect(screen.queryByRole("group", { name: /a\.png/ })).not.toBeInTheDocument());

    await user.click(sendButton());
    expect(onSend.mock.calls[0][0].attached?.map((m) => m.id)).toEqual([42]);
  });

  it("an upload the relay says is not ready fails with its note", async () => {
    const user = userEvent.setup();
    uploadFile.mockResolvedValue({ ready: false, deduped: false, vault_id: null, send_with: [], note: "still processing" });
    await renderComposer();

    await user.upload(fileInput(), png("a.png"));

    const failed = await screen.findByRole("group", { name: "Upload failed: a.png" });
    expect(within(failed).getByText(/still processing/)).toBeInTheDocument();
  });

  it("removing an uploading chip drops it from the sent message, even when its upload lands later", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    const { onSend } = await renderComposer();

    await user.type(textbox(), "hi");
    await user.upload(fileInput(), png("a.png"));
    const chip = screen.getByRole("group", { name: "Uploading a.png" });
    await user.click(within(chip).getByRole("button", { name: "Remove upload" }));

    expect(screen.queryByRole("group", { name: "Uploading a.png" })).not.toBeInTheDocument();
    expect(sendButton()).toBeEnabled();
    pending[0]?.resolve(ok(888));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByRole("button", { name: "Remove attachment" })).not.toBeInTheDocument();

    await user.click(sendButton());
    expect(onSend.mock.calls[0][0].attached).toBeUndefined();
  });

  it("a file dropped on the Composer uploads; a non-media file is ignored", async () => {
    uploadFile.mockResolvedValue(ok(31));
    const { container } = await renderComposer();
    const area = container.querySelector("[data-composer-area]")!;

    fireEvent.drop(area, { dataTransfer: { files: [png("drop.png"), new File(["x"], "notes.txt", { type: "text/plain" })], types: ["Files"] } });

    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    expect((uploadFile.mock.calls[0][1] as File).name).toBe("drop.png");
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove attachment" })).toBeInTheDocument());
  });

  it("an image pasted into the input uploads", async () => {
    uploadFile.mockResolvedValue(ok(32));
    await renderComposer();

    fireEvent.paste(textbox(), { clipboardData: { files: [png("paste.png")], types: ["Files"] } });

    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    expect((uploadFile.mock.calls[0][1] as File).name).toBe("paste.png");
  });

  it("a paste that carries text as well as an image (a spreadsheet's cells) pastes the text and uploads nothing", async () => {
    uploadFile.mockResolvedValue(ok(33));
    await renderComposer();

    const notPrevented = fireEvent.paste(textbox(), {
      clipboardData: { files: [png("cells.png")], types: ["text/plain", "text/html", "Files"], getData: () => "a\tb" },
    });

    expect(notPrevented).toBe(true);
    await new Promise((r) => setTimeout(r, 0));
    expect(uploadFile).not.toHaveBeenCalled();
    expect(screen.queryByRole("group", { name: /cells\.png/ })).not.toBeInTheDocument();
  });

  it("a failed upload blocks Send, Enter and the Timed message until it is retried or removed", async () => {
    const user = userEvent.setup();
    uploadFile.mockRejectedValue(new Error("upstream 500: boom"));
    const { onSend } = await renderComposer();

    await user.type(textbox(), "hi");
    await user.upload(fileInput(), png("a.png"));
    const failed = await screen.findByRole("group", { name: "Upload failed: a.png" });

    expect(sendButton()).toBeDisabled();
    expect(sendButton()).toHaveAttribute("title", "Retry or remove the failed upload first");
    await user.type(textbox(), "{Enter}");
    expect(onSend).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Timed message" }));
    const timed = within(screen.getByRole("region", { name: "Timed message" }));
    await user.type(timed.getByRole("textbox", { name: "Minutes" }), "5");
    expect(timed.getByRole("button", { name: "Start" })).toBeDisabled();
    expect(timed.getByRole("button", { name: "Start" })).toHaveAttribute("title", "Retry or remove the failed upload first");
    await user.click(screen.getByRole("button", { name: "Timed message" }));

    await user.click(within(failed).getByRole("button", { name: "Remove upload" }));
    expect(sendButton()).toBeEnabled();
    await user.click(sendButton());
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend.mock.calls[0][0].attached).toBeUndefined();
  });

  it("an uploaded video gets no blob preview: its tile shows the vault's poster and the send carries none", async () => {
    const user = userEvent.setup();
    uploadFile.mockResolvedValue({
      ready: true, deduped: true, vault_id: 55, send_with: [55],
      existing: { type: "video", files: { thumb: { url: "https://cdn.test/poster.jpg" } } },
    });
    const { onSend, container } = await renderComposer();

    await user.upload(fileInput(), new File(["x"], "clip.mp4", { type: "video/mp4" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove attachment" })).toBeInTheDocument());

    expect(createObjectURL).not.toHaveBeenCalled();
    const srcs = [...container.querySelectorAll("img")].map((i) => i.getAttribute("src") ?? "");
    expect(srcs.some((s) => s.includes(encodeURIComponent("https://cdn.test/poster.jpg")))).toBe(true);
    expect(srcs.some((s) => s.startsWith("blob:"))).toBe(false);
    await user.click(sendButton());
    expect(onSend.mock.calls[0][0].attached?.[0]._localPreview).toBeUndefined();
  });

  it("the Vault picker opens with real vault ids only, and its confirm keeps uploads it cannot know", async () => {
    const user = userEvent.setup();
    const claim = { processId: "p1" };
    const files = { thumb: { url: "https://cdn.test/up.jpg" } };
    uploadFile.mockResolvedValue({
      ready: true, deduped: true, vault_id: 77, send_with: [77, claim], existing: { type: "photo", files },
    });
    const { onSend } = await renderComposer();

    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Remove attachment" })).toHaveLength(2));
    // The picker hands back the uploaded id bare (not on a loaded page) plus a new pick.
    picker.confirm = [{ id: 77, type: "photo" }, { id: 9102, type: "photo" }];
    await user.click(screen.getByRole("button", { name: "Vault" }));
    expect(picker.initialSelectedIds).toEqual([77]);
    await user.click(screen.getByRole("button", { name: "Confirm" }));
    await user.click(sendButton());

    const sent = onSend.mock.calls[0][0].attached ?? [];
    expect(sent.map((m) => m._claim ?? m.id)).toEqual([77, 9102, claim]);
    expect(sent[0]).toMatchObject({ files, _localPreview: "blob:a.png" });
  });

  it("removing or clearing an uploaded attachment revokes its blob preview; sending does not", async () => {
    const user = userEvent.setup();
    uploadFile.mockResolvedValueOnce(ok(1)).mockResolvedValueOnce(ok(2)).mockResolvedValueOnce(ok(3));
    await renderComposer();

    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove attachment" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Remove attachment" }));
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:a.png");

    await user.upload(fileInput(), png("b.png"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove attachment" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:b.png");

    await user.upload(fileInput(), png("c.png"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove attachment" })).toBeInTheDocument());
    await user.click(sendButton());
    expect(revokeObjectURL).not.toHaveBeenCalledWith("blob:c.png");
  });

  it("picking a Script, which replaces the attachments, revokes the uploads' blob previews", async () => {
    const user = userEvent.setup();
    uploadFile.mockResolvedValue(ok(1));
    const { api } = await renderComposer();

    await user.upload(fileInput(), png("a.png"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove attachment" })).toBeInTheDocument());
    act(() => api.current!.applyTemplate({
      source: "local", text: "Synthetic script", displayText: "Synthetic script", mediaCount: 1,
      price: 0, lockedText: false, isWelcome: false, media: [{ id: 9102, type: "photo" }],
      previews: [], taggedUsers: [],
    }));

    expect(revokeObjectURL).toHaveBeenCalledWith("blob:a.png");
  });

  it("leaving the chat stops queued uploads and revokes the chips' blob previews", async () => {
    const user = userEvent.setup();
    const pending = queueUploads();
    const { unmount } = await renderComposer();

    await user.upload(fileInput(), [png("a.png"), png("b.png")]);
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:a.png");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:b.png");

    pending[0].resolve(ok(1));
    await new Promise((r) => setTimeout(r, 0));
    expect(uploadFile).toHaveBeenCalledTimes(1);
  });
});
