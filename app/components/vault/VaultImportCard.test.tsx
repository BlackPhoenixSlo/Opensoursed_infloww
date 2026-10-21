import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), uploadForm: vi.fn() } };
});
vi.mock("@/components/vault/VaultAccount", () => ({
  useVaultAccountId: () => "1000001",
  useVaultAccount: () => ({
    account: { id: "1000001", nickname: "Placeholder Creator" },
    sessionLost: false,
  }),
}));

import VaultImportCard, { detailsNote, itemLabel, runSummary, showsError } from "./VaultImportCard";
import { metaToWire } from "./VaultImportDetails";
import { relay } from "@/lib/relay";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";

// The selection bar's tour shows once per browser (the bundle's "vaultProOnboarding" store); every test but the
// tour's own starts with it seen, so no tour overlays the card under test.
beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("vaultProOnboarding", JSON.stringify({ batchEdit: "1", uploadBtn: "1" }));
});

/** Wait until the card's status read has been made and its (mocked, instant) answer has rendered. */
async function statusAnswered() {
  await waitFor(() => expect(relay.get).toHaveBeenCalledWith("/api/of/v2/vault/upload/status", expect.anything()));
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
}

/**
 * The two pure formatters, kept separate from the polling component so the
 * wording can be tested without a query client. What matters here is that the
 * panel never overstates what happened: a deduped file is not an upload, an
 * interrupted run is not a finished one, and a failure shows the server's own
 * reason rather than a generic "error".
 */

const base = {
  name: "clip.mov",
  source: "local" as const,
  size: 1_000_000,
  status: "pending" as const,
  error: null,
  vault_id: null,
  deduped: null,
};

describe("itemLabel", () => {
  it("says a deduped file was already there, not that it uploaded", () => {
    expect(itemLabel({ ...base, status: "done", deduped: true, vault_id: 42 }))
      .toBe("already in vault");
  });

  it("shows the vault id for a real upload", () => {
    expect(itemLabel({ ...base, status: "done", deduped: false, vault_id: 42 }))
      .toBe("in vault · 42");
  });

  it("says a still-encoding upload is not yet playable, rather than plain done", () => {
    // The vault id is real and permanent — OnlyFans finishes the encode on its
    // own — but a chatter who sends it right now gets a broken attachment.
    expect(itemLabel({ ...base, status: "done", deduped: false, vault_id: 42,
                       still_transcoding: true }))
      .toBe("in vault · 42 · still processing");
  });

  it("surfaces the server's reason for a skip rather than a generic word", () => {
    expect(itemLabel({ ...base, status: "skipped", error: "465 MB is over the 200 MB limit" }))
      .toBe("465 MB is over the 200 MB limit");
  });

  it("falls back to a plain word when the server gave no reason", () => {
    expect(itemLabel({ ...base, status: "skipped" })).toBe("skipped");
    expect(itemLabel({ ...base, status: "failed" })).toBe("failed");
  });

  it("shows the error for a failure", () => {
    expect(itemLabel({ ...base, status: "failed", error: "claim failed: 504" }))
      .toBe("claim failed: 504");
  });
});

describe("runSummary", () => {
  it("says nothing has run when there is no run", () => {
    expect(runSummary({ running: false })).toBe("No import has run yet.");
  });

  it("names the phase while collecting, since no upload has started yet", () => {
    expect(runSummary({ running: true, run_id: "r", phase: "collecting", done: 0, total: 5 }))
      .toBe("fetching files — 0 of 5 done");
  });

  it("counts progress while uploading", () => {
    expect(runSummary({ running: true, run_id: "r", phase: "uploading", done: 2, total: 5 }))
      .toBe("uploading — 2 of 5 done");
  });

  it("does not report an interrupted run as finished", () => {
    expect(runSummary({ running: false, run_id: "r", status: "interrupted", done: 3, total: 5 }))
      .toContain("Interrupted");
  });

  it("reports failures and skips alongside successes", () => {
    expect(runSummary({ running: false, run_id: "r", status: "done", done: 3, failed: 1, skipped: 2 }))
      .toBe("3 in vault · 1 failed · 2 skipped");
  });

  it("stays quiet about zero failures", () => {
    expect(runSummary({ running: false, run_id: "r", status: "done", done: 3, failed: 0, skipped: 0 }))
      .toBe("3 in vault");
  });
});

describe("metaToWire", () => {
  it("sends nothing for a row left blank", () => {
    expect(metaToWire(undefined)).toBeNull();
    expect(metaToWire({ hashtags: " ", notes: "", price: "" })).toBeNull();
  });

  it("splits tags on commas only, strips their marks and reads the price in dollars", () => {
    // Commas only, as the relay reads them: "red set" is one hashtag, as a
    // Drive folder of that name is.
    expect(
      metaToWire({ category: "12", tag: "@alice, bob", hashtags: "#red set,#beach, #beach", notes: " red set ", price: "$12.50" }),
    ).toEqual({
      list_id: 12,
      tag_creators: ["alice", "bob"],
      hashtags: ["red set", "beach"],
      notes: "red set",
      price_cents: 1250,
    });
  });

  it("drops a price that is not a number", () => {
    expect(metaToWire({ price: "free" })).toBeNull();
  });
});

describe("detailsNote", () => {
  it("says how many files' details were not saved, and why", () => {
    expect(detailsNote({ details_saved: { applied: 1, skipped: 2, why: "not synced" } })).toBe(
      "Details for 2 files were not saved: not synced.",
    );
  });

  it("stays quiet when every file's details were saved, or none were given", () => {
    expect(detailsNote({ details_saved: { applied: 3, skipped: 0, why: null } })).toBeNull();
    expect(detailsNote({ details_saved: null })).toBeNull();
  });
});

describe("showsError", () => {
  const DAY = 24 * 60 * 60 * 1000;
  const now = Date.parse("2026-09-08T12:00:00Z");

  it("shows a fresh failure", () => {
    expect(showsError(
      { running: false, run_id: "r", status: "failed", error: "no disk",
        finished_at: "2026-09-08T11:00:00Z" }, now)).toBe(true);
  });

  it("stops showing a failure from last week on every page load", () => {
    expect(showsError(
      { running: false, run_id: "r", status: "failed", error: "no disk",
        finished_at: new Date(now - 7 * DAY).toISOString() }, now)).toBe(false);
  });

  it("never shows an error banner over a run that succeeded", () => {
    expect(showsError(
      { running: false, run_id: "r", status: "done", error: "stale text",
        finished_at: new Date(now - 60_000).toISOString() }, now)).toBe(false);
  });

  it("has nothing to show when there is no error", () => {
    expect(showsError({ running: false, run_id: "r", status: "failed" }, now)).toBe(false);
  });
});

/**
 * The Drive slot (docs/spec/infloww-parity-round-2/phase-05-drive-import.md,
 * Seam 1; ticket 46). The status read the card already polls says whether the
 * server's GOOGLE_DRIVE_API_KEY is set: only `true` shows a closed, labelled
 * "Import from Google Drive" section, after the three steps and right above
 * Start (page-parity ticket 10, the owner's "move it lower"); false, absent or
 * no answer yet is nothing at all. The relay is mocked by path, so nothing
 * reaches `fetch`.
 */
describe("VaultImportCard Drive slot", () => {
  const relayGet = relay.get as unknown as Mock;
  const relayUpload = relay.uploadForm as unknown as Mock;
  const STATUS = "/api/of/v2/vault/upload/status";

  /** Answer the status read with `status` (or never, for `"pending"`), and the
   *  folder list with no folders. */
  function serve(status: Record<string, unknown> | "pending") {
    relayGet.mockImplementation((path: string) => {
      if (path.startsWith(STATUS)) {
        return status === "pending" ? new Promise(() => {}) : Promise.resolve(status);
      }
      return Promise.resolve({ list: [], hasMore: false });
    });
  }

  function renderCard() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <VaultImportCard />
      </QueryClientProvider>,
    );
  }

  const startButton = () => screen.getByRole("button", { name: /Start import/ });

  beforeEach(() => {
    relayGet.mockReset();
    relayUpload.mockReset();
    relayUpload.mockResolvedValue({ run_id: "r1" });
  });
  afterEach(() => cleanup());

  it("with the key set, shows a closed, labelled section after the Edit media step whose links go out with Start import", async () => {
    serve({ running: false, run: null, drive_import_configured: true });
    const user = userEvent.setup();
    const { container } = renderCard();

    const summary = await screen.findByText(/Import from Google Drive/, { selector: "summary" });
    const details = summary.closest("details")!;
    const steps = screen.getByRole("list", { name: "Upload steps" });
    const editMedia = within(steps).getByRole("heading", { name: "Edit media" });
    expect(steps.contains(details)).toBe(false);
    expect(editMedia.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(details.compareDocumentPosition(startButton()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container.querySelector('input[type="file"]')!.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(details.open).toBe(false);
    expect(summary.textContent).toContain(EXTRA_LABEL);
    expect(summary.getAttribute("title")).toBe(EXTRA_LABEL);

    const box = container.querySelector("textarea")!;
    expect(box).not.toBeVisible();
    await user.click(summary);
    expect(box).toBeVisible();

    const link = "https://drive.google.com/drive/folders/placeholder-folder";
    await user.type(box, link);
    await user.click(startButton());
    await waitFor(() => expect(relayUpload).toHaveBeenCalledTimes(1));
    const form = relayUpload.mock.calls[0][1] as FormData;
    expect(form.get("drive_links")).toBe(link);
  });

  it.each([
    ["false", { running: false, run: null, drive_import_configured: false }],
    ["absent", { running: false, run: null }],
  ])("with the field %s, renders nothing Drive-related", async (_name, status) => {
    serve(status);
    const { container } = renderCard();
    await statusAnswered();

    expect(screen.queryByText(/Google Drive|GOOGLE_DRIVE_API_KEY/)).toBeNull();
    expect(container.querySelector("details")).toBeNull();
    expect(container.querySelector("textarea")).toBeNull();
    expect(screen.queryByText(/Import from Google Drive/, { selector: "summary" })).toBeNull();
    expect(startButton()).toBeDisabled();
  });

  it("says the folder must be shared by link, and List files previews each file with its folder hashtags", async () => {
    const listing = {
      files: [
        { name: "a.jpg", size: 10, mime_type: "image/jpeg", folders: ["Shoot", "Beach"], hashtags: ["beach"], importable: true, reason: null },
        { name: "notes.pdf", size: 5, mime_type: "application/pdf", folders: ["Shoot"], hashtags: ["shoot"], importable: false, reason: "not a photo, video or audio file" },
      ],
      max_files: 50,
    };
    relayGet.mockImplementation((path: string) => {
      if (path.startsWith(STATUS)) return Promise.resolve({ running: false, run: null, drive_import_configured: true });
      if (path.startsWith("/api/of/v2/vault/upload/drive/list")) return Promise.resolve(listing);
      return Promise.resolve({ list: [], hasMore: false });
    });
    const user = userEvent.setup();
    const { container } = renderCard();
    await user.click(await screen.findByText(/Import from Google Drive/, { selector: "summary" }));
    expect(screen.getByText(/Anyone with the link/).closest("p")!.textContent).toContain("can view");

    const link = "https://drive.google.com/drive/folders/placeholder-folder";
    await user.type(container.querySelector("textarea")!, link);
    await user.click(screen.getByRole("button", { name: "List files" }));
    const list = await screen.findByRole("list", { name: "Drive files" });
    expect(relayGet).toHaveBeenCalledWith(
      `/api/of/v2/vault/upload/drive/list?link=${encodeURIComponent(link)}`,
      expect.anything(),
    );
    expect(within(list).getByText("#beach")).toBeInTheDocument();
    expect(within(list).getByText("not a photo, video or audio file")).toBeInTheDocument();
    expect(screen.getByText(/1 to import · 1 skipped/)).toBeInTheDocument();
  });

  it("past the run's file limit, says how many this run takes", async () => {
    const jpg = (name: string) => ({ name, size: 10, hashtags: [], importable: true, reason: null });
    relayGet.mockImplementation((path: string) => {
      if (path.startsWith(STATUS)) return Promise.resolve({ running: false, run: null, drive_import_configured: true });
      if (path.startsWith("/api/of/v2/vault/upload/drive/list"))
        return Promise.resolve({ files: [jpg("a.jpg"), jpg("b.jpg"), jpg("c.jpg")], max_files: 2 });
      return Promise.resolve({ list: [], hasMore: false });
    });
    const user = userEvent.setup();
    const { container } = renderCard();
    await user.click(await screen.findByText(/Import from Google Drive/, { selector: "summary" }));
    await user.type(container.querySelector("textarea")!, "https://drive.google.com/drive/folders/x");
    await user.click(screen.getByRole("button", { name: "List files" }));
    expect(await screen.findByText("3 to import (first 2 this run)")).toBeInTheDocument();
    // Edited links are not the links that were listed.
    await user.type(container.querySelector("textarea")!, "y");
    expect(screen.queryByText(/to import/)).toBeNull();
  });

  it("shows the relay's reason when a Drive link cannot be read", async () => {
    relayGet.mockImplementation((path: string) => {
      if (path.startsWith(STATUS)) return Promise.resolve({ running: false, run: null, drive_import_configured: true });
      if (path.startsWith("/api/of/v2/vault/upload/drive/list")) return Promise.reject(new Error("Drive link not found — share it as anyone with the link"));
      return Promise.resolve({ list: [], hasMore: false });
    });
    const user = userEvent.setup();
    const { container } = renderCard();
    await user.click(await screen.findByText(/Import from Google Drive/, { selector: "summary" }));
    await user.type(container.querySelector("textarea")!, "https://drive.google.com/drive/folders/x");
    await user.click(screen.getByRole("button", { name: "List files" }));
    expect(await screen.findByText(/Drive link not found/)).toBeInTheDocument();
  });

  it("while the status read is pending, renders neither the line nor a link box", async () => {
    serve("pending");
    const { container } = renderCard();
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(relayGet).toHaveBeenCalledWith(STATUS, expect.anything());
    expect(screen.queryByText(/GOOGLE_DRIVE_API_KEY/)).toBeNull();
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.querySelector("details")).toBeNull();
  });
});

/**
 * The file drop and the card's kept elements (phase-05 spec, Seam 1, cases 2c,
 * 3 and 4; ticket 47). The file drop leads the card in the capture's words
 * (docs/infloww-layouts/growth-vault-pro.md: "Select media" #90, "Add media"
 * #95, the tip #97), takes dragged files into the same picked list as the
 * picker, and refuses them while a run is live. The header no longer mentions
 * Google Drive. The card's own elements with no capture item carry the shared
 * "Inflowwww extra" tooltip.
 */
describe("VaultImportCard file drop", () => {
  const relayGet = relay.get as unknown as Mock;
  const STATUS = "/api/of/v2/vault/upload/status";
  const TIP = "Drag and drop media file(s) here or select them from your computer";

  function serve(status: Record<string, unknown>) {
    relayGet.mockImplementation((path: string) =>
      Promise.resolve(path.startsWith(STATUS) ? status : { list: [], hasMore: false }),
    );
  }

  function renderCard() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <VaultImportCard />
      </QueryClientProvider>,
    );
  }

  const dropArea = () => screen.getByRole("group", { name: "Select media" });
  const clip = () => new File(["placeholder bytes"], "clip.mp4", { type: "video/mp4" });

  beforeEach(() => {
    relayGet.mockReset();
  });
  afterEach(() => cleanup());

  it("leads with the capture's file drop, then the folder, the Drive section and the Start row", async () => {
    serve({ running: false, run: null, drive_import_configured: true });
    const { container } = renderCard();
    const summary = await screen.findByText(/Import from Google Drive/, { selector: "summary" });

    const area = dropArea();
    expect(within(area).getByText(TIP)).toBeInTheDocument();
    expect(within(area).getByText("Add media")).toBeInTheDocument();
    expect(area.contains(container.querySelector('input[type="file"]'))).toBe(true);

    const order = [area, screen.getByText("Put into folder"), summary, screen.getByRole("button", { name: /Start import/ })];
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it("the header copy no longer mentions Google Drive", async () => {
    serve({ running: false, run: null, drive_import_configured: false });
    const { container } = renderCard();
    await statusAnswered();

    const header = container.querySelector("header")!;
    expect(header.textContent).toContain("Nothing is posted or sent to fans.");
    expect(header.textContent).not.toContain("Google Drive");
  });

  it("a file dropped on the drop area counts as picked", async () => {
    serve({ running: false, run: null });
    renderCard();
    await statusAnswered();

    fireEvent.drop(dropArea(), { dataTransfer: { files: [clip()], types: ["Files"] } });
    expect(await screen.findByText(/^1 file ·/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start import/ })).toBeEnabled();
  });

  it("refuses a dropped file while a run is live", async () => {
    serve({ running: true, run_id: "r1", status: "running", phase: "uploading", done: 0, total: 2 });
    renderCard();
    await screen.findByText("uploading — 0 of 2 done");

    fireEvent.drop(dropArea(), { dataTransfer: { files: [clip()], types: ["Files"] } });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.queryByText(/^1 file ·/)).toBeNull();
  });

  it("every kept element with no capture item carries the shared extra label as its tooltip", async () => {
    // A live run with a filing warning, so the progress and warnings render.
    serve({
      running: true, run_id: "r1", status: "running", phase: "uploading", done: 1, total: 2,
      filing_error: "Placeholder folder is gone",
      items: [{ ...base, name: "clip.mp4", status: "uploading" }],
    });
    renderCard();
    await screen.findByText("uploading — 1 of 2 done");

    const tooltip = (el: HTMLElement) => el.closest("[title]")?.getAttribute("title");
    // The target Creator in the title.
    expect(tooltip(screen.getByRole("heading", { name: /Import to Placeholder Creator/ }))).toBe(EXTRA_LABEL);
    // The re-encode and "nothing is posted" sentences.
    expect(tooltip(screen.getByText(/Large video is re-encoded/))).toBe(EXTRA_LABEL);
    // "Put into folder".
    expect(tooltip(screen.getByText("Put into folder"))).toBe(EXTRA_LABEL);
    // The Start import row and the run's progress and warnings.
    expect(tooltip(screen.getByRole("button", { name: /Importing/ }))).toBe(EXTRA_LABEL);
    expect(tooltip(screen.getByText("uploading — 1 of 2 done"))).toBe(EXTRA_LABEL);
    expect(tooltip(screen.getByText(/Each new file costs two paced writes/))).toBe(EXTRA_LABEL);
    expect(tooltip(screen.getByText(/Placeholder folder is gone/))).toBe(EXTRA_LABEL);
    expect(tooltip(screen.getByText("uploading…"))).toBe(EXTRA_LABEL);
  });

  it("a run with a linked fan says each file costs one write, not two", async () => {
    serve({ running: true, run_id: "r1", status: "running", phase: "uploading", done: 0, total: 1, fan_id: 4242 });
    renderCard();
    expect(await screen.findByText(/Each new file costs one paced write — the chat message to the fan/)).toBeInTheDocument();
    expect(screen.queryByText(/two paced writes/)).toBeNull();
  });

  it("the picked line carries the shared extra label as its tooltip", async () => {
    serve({ running: false, run: null });
    renderCard();
    await statusAnswered();

    fireEvent.drop(dropArea(), { dataTransfer: { files: [clip()], types: ["Files"] } });
    const line = await screen.findByText(/^1 file ·/);
    expect(line.closest("[title]")?.getAttribute("title")).toBe(EXTRA_LABEL);
  });
});

/**
 * The capture's steps around the file drop (ticket 58; docs/infloww-layouts/growth-vault-pro.md #81 to #119). Step 1,
 * "Link a fan account", is optional here: a username sends each file to that fan (Infloww's way, #86); empty files it
 * through a scheduled post the relay deletes again. The rules row gives this server's own limits from the status read, never
 * Infloww's 4 GB / 100 MB / pixel rules (#99 to #105), and names the narrower set of kinds the drop takes (#93).
 * Step 3, "Edit media", lists the picked files under the capture's columns; every field goes up with its file as
 * `meta`. Several files start one run and append the rest. The selection bar and Batch edit follow the capture
 * (#112 to #117).
 */
describe("VaultImportCard steps", () => {
  const relayGet = relay.get as unknown as Mock;
  const relayUpload = relay.uploadForm as unknown as Mock;
  const STATUS = "/api/of/v2/vault/upload/status";
  const LIMITS = { max_file_mb: 1234, max_files: 7 };

  function serve(status: Record<string, unknown>) {
    relayGet.mockImplementation((path: string) =>
      Promise.resolve(path.startsWith(STATUS) ? status : { list: [], hasMore: false }),
    );
  }

  /** Render the card on `status` and wait for the status answer. */

  async function ready(status: Record<string, unknown> = { running: false, run: null, upload_limits: LIMITS }) {
    serve(status);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <VaultImportCard />
      </QueryClientProvider>,
    );
    await statusAnswered();
  }

  const file = (name: string, type: string) => new File(["placeholder bytes"], name, { type });
  const drop = (...files: File[]) =>
    fireEvent.drop(screen.getByRole("group", { name: "Select media" }), { dataTransfer: { files, types: ["Files"] } });

  beforeEach(() => {
    relayGet.mockReset();
    relayUpload.mockReset();
    relayUpload.mockResolvedValue({ run_id: "r1" });
  });
  afterEach(() => cleanup());

  it("draws the three steps in order, with step 1 an optional, editable username", async () => {
    await ready();

    const steps = screen.getByRole("list", { name: "Upload steps" });
    const titles = within(steps).getAllByRole("heading").map((h) => h.textContent);
    expect(titles).toEqual(["Link a fan account (optional)", "Select media", "Edit media"]);

    expect(screen.getByText("OnlyFans account")).toBeInTheDocument();
    const account = screen.getByPlaceholderText("Enter OnlyFans username");
    expect(account).toBeEnabled();
    const tip = screen.getByLabelText("About linking a fan account").getAttribute("title")!;
    expect(tip).toContain("Infloww will automatically send media to this account");
    expect(tip).toContain("scheduled post that is deleted");
    expect(screen.getByText(/Empty: each new file rides a scheduled post/)).toBeInTheDocument();
  });

  it("with no username the import goes without a fan; a typed one must be checked, and the checked one is sent", async () => {
    const FAN = "/api/of/v2/vault/upload/fan";
    relayGet.mockImplementation((path: string) => {
      if (path.startsWith(STATUS)) return Promise.resolve({ running: false, run: null, upload_limits: LIMITS });
      if (path === `${FAN}?username=%40placeholderfan`)
        return Promise.resolve({ id: 4242, username: "placeholderfan", name: "Placeholder Fan" });
      if (path.startsWith(FAN)) return Promise.reject(new Error("No OnlyFans account @nobody — check the username"));
      return Promise.resolve({ list: [], hasMore: false });
    });
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <VaultImportCard />
      </QueryClientProvider>,
    );
    await statusAnswered();
    drop(file("still.jpg", "image/jpeg"));
    await user.click(await screen.findByRole("button", { name: /Start import/ }));
    await waitFor(() => expect(relayUpload).toHaveBeenCalledTimes(1));
    expect((relayUpload.mock.calls[0][1] as FormData).has("fan_username")).toBe(false);

    drop(file("clip.mp4", "video/mp4"));
    const account = screen.getByLabelText("OnlyFans account");
    // Unknown: said as such, and Start stays off.
    await user.type(account, "nobody");
    await user.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText(/No OnlyFans account @nobody/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start import/ })).toBeDisabled();

    await user.clear(account);
    await user.type(account, "@placeholderfan");
    expect(screen.getByRole("button", { name: /Start import/ })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Check" }));
    expect(await screen.findByText(/Will send to Placeholder Fan \(@placeholderfan\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Start import/ }));
    await waitFor(() => expect(relayUpload).toHaveBeenCalledTimes(2));
    const form = relayUpload.mock.calls[1][1] as FormData;
    expect(form.get("fan_username")).toBe("placeholderfan");
    expect(form.get("fan_id")).toBe("4242");

    // An edit after the check is a different name: checked again before any send.
    await user.type(account, "x");
    expect(screen.queryByText(/Will send to/)).toBeNull();
    expect(screen.getByRole("button", { name: "Check" })).toBeInTheDocument();
  });

  it("names the columns that will not be saved when this vault is not synced here, and says what the run did not save", async () => {
    await ready({
      running: false, run_id: "r1", status: "done", done: 1, total: 1, items: [],
      details_saved_here: false,
      details_saved: { applied: 0, skipped: 1, why: "this model's vault is not synced here yet" },
    });
    drop(file("still.jpg", "image/jpeg"));
    const table = await screen.findByRole("table");
    const heads = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual([
      "", "Media", "Category", "Tag Creators· not saved", "Hashtags· not saved", "Notes· not saved",
      "Suggested price· not saved", "Action",
    ]);
    expect(screen.getByText(/Details for 1 file were not saved: this model's vault is not synced here yet/)).toBeInTheDocument();
  });

  it("locks the rows and Batch edit while a batch is still going up", async () => {
    let release: (v: unknown) => void = () => {};
    relayUpload.mockImplementation((path: string) =>
      path.endsWith("/append") ? new Promise((r) => (release = r)) : Promise.resolve({ run_id: "r1" }),
    );
    const user = userEvent.setup();
    await ready();
    drop(file("a.jpg", "image/jpeg"), file("b.jpg", "image/jpeg"));
    const bar = await screen.findByRole("region", { name: "Selected media" });
    await user.click(within(bar).getByRole("button", { name: "Bulk upload" }));
    await waitFor(() => expect(relayUpload).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Hashtags for b.jpg")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Batch edit" })).toBeDisabled();
    await act(async () => release({}));
    await waitFor(() => expect(screen.queryByRole("table")).toBeNull());
  });

  it("the rules row gives this server's limits and the kinds the drop takes, labelled as ours", async () => {
    await ready();

    const row = screen.getByRole("list", { name: "Upload rules" });
    expect(row.getAttribute("title")).toBe(EXTRA_LABEL);
    expect(row.textContent).toContain("File size limit: 1234MB");
    expect(row.textContent).toContain("Files per import: 7");
    expect(row.textContent).toContain("Images, GIF, video and audio");
    for (const theirs of ["4GB", "100MB", "10,000px"]) expect(row.textContent).not.toContain(theirs);
  });

  it("without the relay's limits the row names only the kinds, with no size or count", async () => {
    await ready({ running: false, run: null });

    const row = screen.getByRole("list", { name: "Upload rules" });
    expect(row.textContent).toContain("Images, GIF, video and audio");
    expect(row.textContent).not.toMatch(/size limit|per import/);
  });

  it("a dropped PDF is not taken, as the rules row says", async () => {
    await ready();

    drop(file("placeholder.pdf", "application/pdf"));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.queryByText(/^1 file ·/)).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("step 3 lists each picked file under the capture's columns, every field editable", async () => {
    await ready();
    drop(file("clip.mp4", "video/mp4"), file("still.jpg", "image/jpeg"));

    const table = await screen.findByRole("table");
    const heads = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(heads).toEqual(["", "Media", "Category", "Tag Creators", "Hashtags", "Notes", "Suggested price", "Action"]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("clip.mp4")).toBeInTheDocument();
    for (const field of ["Category", "Tag Creators", "Hashtags", "Notes", "Suggested price"]) {
      expect(within(rows[0]).getByLabelText(`${field} for clip.mp4`)).toBeEnabled();
    }
  });

  it("a row's details go up with its file as meta", async () => {
    const user = userEvent.setup();
    await ready();
    drop(file("still.jpg", "image/jpeg"));
    await user.type(await screen.findByLabelText("Hashtags for still.jpg"), "beach, #red");
    await user.type(screen.getByLabelText("Tag Creators for still.jpg"), "@alice");
    await user.type(screen.getByLabelText("Suggested price for still.jpg"), "9.99");
    await user.click(screen.getByRole("button", { name: /Start import/ }));
    await waitFor(() => expect(relayUpload).toHaveBeenCalledTimes(1));
    const form = relayUpload.mock.calls[0][1] as FormData;
    expect(JSON.parse(form.get("meta") as string)).toEqual([
      { hashtags: ["beach", "red"], tag_creators: ["alice"], price_cents: 999 },
    ]);
  });

  it("Bulk upload of several files starts the run with the first and appends the rest, the last closing it", async () => {
    const user = userEvent.setup();
    await ready();
    drop(file("a.jpg", "image/jpeg"), file("b.jpg", "image/jpeg"), file("c.jpg", "image/jpeg"));
    const bar = await screen.findByRole("region", { name: "Selected media" });
    await user.click(within(bar).getByRole("button", { name: "Bulk upload" }));
    await waitFor(() => expect(relayUpload).toHaveBeenCalledTimes(3));

    const [first, second, third] = relayUpload.mock.calls;
    expect(first[0]).toBe("/api/of/v2/vault/upload/batch");
    const f1 = first[1] as FormData;
    expect((f1.getAll("files") as File[]).map((f) => f.name)).toEqual(["a.jpg"]);
    expect(f1.get("keep_open")).toBe("1");
    for (const [call, name, last] of [[second, "b.jpg", false], [third, "c.jpg", true]] as const) {
      expect(call[0]).toBe("/api/of/v2/vault/upload/batch/append");
      const f = call[1] as FormData;
      expect(f.get("run_id")).toBe("r1");
      expect((f.getAll("files") as File[]).map((x) => x.name)).toEqual([name]);
      expect(f.has("last")).toBe(last);
    }
    await waitFor(() => expect(screen.queryByRole("table")).toBeNull());
  });

  it("a single file goes in one call, not held open", async () => {
    const user = userEvent.setup();
    await ready();
    drop(file("a.jpg", "image/jpeg"));
    await user.click(await screen.findByRole("button", { name: /Start import/ }));
    await waitFor(() => expect(relayUpload).toHaveBeenCalledTimes(1));
    expect((relayUpload.mock.calls[0][1] as FormData).has("keep_open")).toBe(false);
  });

  it("a row's Delete takes that file off the list", async () => {
    const user = userEvent.setup();
    await ready();
    drop(file("clip.mp4", "video/mp4"), file("still.jpg", "image/jpeg"));

    await user.click(await screen.findByRole("button", { name: "Delete clip.mp4" }));
    expect(screen.queryByText("clip.mp4")).toBeNull();
    expect(screen.getByText("still.jpg")).toBeInTheDocument();
  });

  it("picked files start selected; the bar counts them and Bulk upload sends only the selected ones", async () => {
    const user = userEvent.setup();
    await ready();
    drop(file("clip.mp4", "video/mp4"), file("still.jpg", "image/jpeg"));

    const bar = await screen.findByRole("region", { name: "Selected media" });
    expect(bar.textContent).toContain("Selected");
    expect(within(bar).getByText("2")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Select clip.mp4" }));
    expect(within(bar).getByText("1")).toBeInTheDocument();
    await user.click(within(bar).getByRole("button", { name: "Bulk upload" }));
    await waitFor(() => expect(relayUpload).toHaveBeenCalledTimes(1));
    const form = relayUpload.mock.calls[0][1] as FormData;
    expect((form.getAll("files") as File[]).map((f) => f.name)).toEqual(["still.jpg"]);
    // The sent file leaves the list; the one left unselected stays for later.
    await waitFor(() => expect(screen.queryByText("still.jpg")).toBeNull());
    expect(screen.getByText("clip.mp4")).toBeInTheDocument();
  });

  it("with nothing selected the bar goes and Start import is off", async () => {
    const user = userEvent.setup();
    await ready();
    drop(file("clip.mp4", "video/mp4"));

    const bar = await screen.findByRole("region", { name: "Selected media" });
    await user.click(within(bar).getByRole("button", { name: "Clear selection" }));
    expect(screen.queryByRole("region", { name: "Selected media" })).toBeNull();
    expect(screen.getByRole("button", { name: /Start import/ })).toBeDisabled();
  });

  it("the bar's delete takes the selected files off the list", async () => {
    const user = userEvent.setup();
    await ready();
    drop(file("clip.mp4", "video/mp4"), file("still.jpg", "image/jpeg"));

    await user.click(await screen.findByRole("checkbox", { name: "Select still.jpg" }));
    await user.click(screen.getByRole("button", { name: "Delete selected" }));
    expect(screen.queryByText("clip.mp4")).toBeNull();
    expect(screen.getByText("still.jpg")).toBeInTheDocument();
  });

  it("Batch edit opens the capture's modal, and Cancel closes it without changing a row", async () => {
    const user = userEvent.setup();
    await ready();
    drop(file("clip.mp4", "video/mp4"));

    await user.click(await screen.findByRole("button", { name: "Batch edit" }));
    const dialog = screen.getByRole("dialog", { name: "Batch edit media" });
    expect(within(dialog).getByText("Select criteria")).toBeInTheDocument();
    const chip = (name: string) => within(dialog).getByRole("button", { name });
    // Hashtags and Notes start ticked (`defaultSelectTags`, #115).
    expect(chip("Hashtags").getAttribute("aria-pressed")).toBe("true");
    expect(chip("Notes").getAttribute("aria-pressed")).toBe("true");
    expect(chip("Price").getAttribute("aria-pressed")).toBe("false");
    const notes = within(dialog).getByPlaceholderText("Briefly describe the media content");
    expect(notes).toBeEnabled();
    await user.type(notes, "discarded");
    expect(within(dialog).queryByText("Suggested price")).toBeNull();

    await user.click(chip("Price"));
    expect(within(dialog).getByText("Suggested price")).toBeInTheDocument();
    await user.click(chip("All"));
    expect(chip("All").getAttribute("aria-pressed")).toBe("true");
    expect(within(dialog).getByLabelText("Tag other Creator(s)")).toBeEnabled();

    expect(within(dialog).getByText("Saving will update the details for all selected media")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Save" })).toBeEnabled();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByLabelText("Notes for clip.mp4")).toHaveValue("");
  });

  it("Batch edit's Save writes the shown fields onto every selected row only", async () => {
    const user = userEvent.setup();
    await ready();
    drop(file("clip.mp4", "video/mp4"), file("still.jpg", "image/jpeg"));
    await user.type(await screen.findByLabelText("Suggested price for still.jpg"), "5");
    await user.click(screen.getByRole("checkbox", { name: "Select clip.mp4" }));

    await user.click(screen.getByRole("button", { name: "Batch edit" }));
    const dialog = screen.getByRole("dialog", { name: "Batch edit media" });
    await user.type(within(dialog).getByLabelText("Hashtags"), "beach");
    await user.type(within(dialog).getByLabelText("Notes"), "red set");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    expect(screen.getByLabelText("Hashtags for still.jpg")).toHaveValue("beach");
    expect(screen.getByLabelText("Notes for still.jpg")).toHaveValue("red set");
    // A field the modal did not show is left as it was.
    expect(screen.getByLabelText("Suggested price for still.jpg")).toHaveValue("5");
    expect(screen.getByLabelText("Hashtags for clip.mp4")).toHaveValue("");
  });

  /* The selection bar's tour (the bundle's `useMultipleSelectionOperationOnboarding`, index.9f50f370.js @12947586):
     the first time the bar shows, "Got it" walks Batch edit, then Bulk upload. */
  const seen = () => JSON.parse(window.localStorage.getItem("vaultProOnboarding") || "{}");
  const STEP1 = "With your media selected, click here to batch-edit their details";
  const STEP2 = "Once you’re ready, click here to upload your selected media file(s)";

  it("the first time the bar shows, its tour walks Batch edit then Bulk upload, each closed by Got it", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    await ready();
    expect(screen.queryByRole("dialog", { name: "Guided tour" })).toBeNull();
    drop(file("clip.mp4", "video/mp4"));

    const tour = await screen.findByRole("dialog", { name: "Guided tour" });
    expect(within(tour).getByText(STEP1)).toBeInTheDocument();
    // Marked on show, as the bundle does; the second step's key is marked only when that step opens a tour itself.
    expect(seen()).toEqual({ batchEdit: "1" });
    await user.click(within(tour).getByRole("button", { name: "Got it" }));
    expect(within(tour).getByText(STEP2)).toBeInTheDocument();
    await user.click(within(tour).getByRole("button", { name: "Got it" }));
    expect(screen.queryByRole("dialog", { name: "Guided tour" })).toBeNull();
    expect(relayUpload).not.toHaveBeenCalled();
  });

  it("with Batch edit's step seen, opens on Bulk upload's; Bulk upload closes it and marks it seen", async () => {
    window.localStorage.setItem("vaultProOnboarding", JSON.stringify({ batchEdit: "1" }));
    const user = userEvent.setup();
    await ready();
    drop(file("clip.mp4", "video/mp4"));

    const tour = await screen.findByRole("dialog", { name: "Guided tour" });
    expect(within(tour).getByText(STEP2)).toBeInTheDocument();
    expect(seen()).toEqual({ batchEdit: "1", uploadBtn: "1" });
    await user.click(within(screen.getByRole("region", { name: "Selected media" })).getByRole("button", { name: "Bulk upload" }));
    expect(screen.queryByRole("dialog", { name: "Guided tour" })).toBeNull();
  });

  it("Batch edit closes the tour and marks its step seen", async () => {
    window.localStorage.clear();
    const user = userEvent.setup();
    await ready();
    drop(file("clip.mp4", "video/mp4"));
    await screen.findByRole("dialog", { name: "Guided tour" });
    await user.click(screen.getByRole("button", { name: "Batch edit" }));
    expect(screen.queryByRole("dialog", { name: "Guided tour" })).toBeNull();
    expect(screen.getByRole("dialog", { name: "Batch edit media" })).toBeInTheDocument();
    expect(seen()).toEqual({ batchEdit: "1" });
  });
});
