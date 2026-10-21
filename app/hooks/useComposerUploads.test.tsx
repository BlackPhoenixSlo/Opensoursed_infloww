/**
 * useComposerUploads' pure halves: which files it takes, and how an upload
 * response becomes Composer attachments. The hook's chips, Retry and per-Fan
 * keeping are pinned through the Composer in
 * `components/chat/ComposerUpload.test.tsx`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { relay } from "@/lib/relay";
import { isUploadable, toAttachments, uploadDeadlineMs, uploadErrorText, uploadToVault } from "./useComposerUploads";

const file = (name: string, type: string) => new File(["x"], name, { type });

describe("useComposerUploads helpers", () => {
  it("takes images and videos only", () => {
    expect(isUploadable(file("a.png", "image/png"))).toBe(true);
    expect(isUploadable(file("a.mp4", "video/mp4"))).toBe(true);
    expect(isUploadable(file("a.txt", "text/plain"))).toBe(false);
    expect(isUploadable(file("a", ""))).toBe(false);
  });

  it("maps vault ids to attachments with the vault's files and claims to claim attachments", () => {
    const claim = { processId: "p" };
    const media = toAttachments(
      {
        ready: true, deduped: true, vault_id: 7, send_with: [7, claim],
        existing: { type: "photo", files: { thumb: { url: "https://cdn/t.jpg" } } },
      },
      file("a.mp4", "video/mp4"),
      "blob:a",
    );

    expect(media[0]).toMatchObject({ id: 7, type: "photo", files: { thumb: { url: "https://cdn/t.jpg" } }, _localPreview: "blob:a" });
    expect(media[1]).toMatchObject({ type: "video", files: null, _claim: claim, _localPreview: "blob:a" });
    expect(media[1].id).toBeLessThan(0);
  });

  it("claim attachments get distinct ids", () => {
    const resp = { ready: true, deduped: false, vault_id: null, send_with: [{ a: 1 }, { a: 2 }] };
    const [a, b] = toAttachments(resp, file("a.png", "image/png"), null);
    expect(a.id).not.toBe(b.id);
  });

  it("throws the relay's note when the upload is not ready, and when it returns no media", () => {
    expect(() => toAttachments(
      { ready: false, deduped: false, vault_id: null, send_with: [], note: "too large" },
      file("a.png", "image/png"), null,
    )).toThrow("too large");
    expect(() => toAttachments(
      { ready: true, deduped: false, vault_id: null, send_with: [] },
      file("a.png", "image/png"), null,
    )).toThrow("Upload returned no media");
  });

  it("words a failure for the chip: OF's status, a short relay note, else a plain line", () => {
    expect(uploadErrorText('upstream 500: {"error":{"code":0,"message":"boom"}}')).toBe("Upload failed — OnlyFans error 500");
    expect(uploadErrorText(
      'bytes in S3 but claim failed: convert register failed: 400 {"error":{"code":0,"message":"Invalid input.","uid":"u"}}',
    )).toBe("Upload failed — OnlyFans refused the file (Invalid input.)");
    expect(uploadErrorText("convert register failed: 413 nope")).toBe("Upload failed — OnlyFans refused the file (error 413)");
    expect(uploadErrorText("still processing")).toBe("Upload failed — still processing");
    expect(uploadErrorText('{"detail":{"a":1}}')).toBe("Upload failed");
    expect(uploadErrorText("x".repeat(90))).toBe("Upload failed");
    expect(uploadErrorText("")).toBe("Upload failed");
  });
});

describe("uploadToVault", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("gives a hung upload a deadline from its turn: it aborts, fails as timed out, and the Creator's queue moves on", async () => {
    vi.useFakeTimers();
    const signals: Array<AbortSignal | undefined> = [];
    // Never settles, signal or not: the deadline alone must free the queue.
    const upload = vi.spyOn(relay, "uploadFile").mockImplementation((...args: unknown[]) => {
      signals.push(args[4] as AbortSignal | undefined);
      return new Promise(() => {});
    });
    const a = file("a.png", "image/png");
    const first = uploadToVault("acct-deadline", a, null).catch((e: Error) => e);
    void uploadToVault("acct-deadline", file("b.png", "image/png"), null).catch(() => undefined);

    await vi.advanceTimersByTimeAsync(uploadDeadlineMs(a.size) - 1);
    expect(upload).toHaveBeenCalledTimes(1);
    expect(signals[0]?.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(1);
    const err = await first;
    expect(err).toBeInstanceOf(Error);
    expect(uploadErrorText((err as Error).message)).toBe("Upload failed — timed out");
    expect(signals[0]?.aborted).toBe(true);
    expect(upload).toHaveBeenCalledTimes(2);
    expect(signals[1]?.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(uploadDeadlineMs(1));
  });

  it("allows a big file longer: two minutes plus 50 KB a second", () => {
    expect(uploadDeadlineMs(0)).toBe(120_000);
    expect(uploadDeadlineMs(500 * 1024 * 1024)).toBe(120_000 + 500 * 1024 * 1024 / 50);
  });
});
