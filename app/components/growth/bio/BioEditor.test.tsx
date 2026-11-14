/**
 * The bio editor over a mocked relay, through the controls the slop UI leg drives: a Display name edit + Save sends
 * only the change and the preview follows the draft; "Add link" sends the dialog's body and the new card shows; "Move
 * up" sends every id in the new order; the custom domain is read-only; an unknown page says so.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return {
    ...mod,
    relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), uploadFile: vi.fn() },
  };
});
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/growth/tracking-links/bio/p1",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));
vi.mock("@/contexts/UserContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/UserContext")>()),
  useUser: () => ({ user: { user_id: "owner-1" } }),
}));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
vi.mock("@/contexts/ChatterContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ChatterContext")>()),
  useChatter: () => ({ chatter: null }),
}));
vi.mock("@/lib/chatterAccounts", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/chatterAccounts")>();
  return { ...mod, chatterAccountsQuery: { ...mod.chatterAccountsQuery, queryFn: async () => [] } };
});

import { BioEditor } from "@/components/growth/bio/BioEditor";
import type { BioLink, BioPage } from "@/hooks/useBioPages";
import { relay, RelayError } from "@/lib/relay";
import { makeTestQueryClient, renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayPatch = relay.patch as unknown as Mock;
const relayPut = relay.put as unknown as Mock;
const relayUpload = relay.uploadFile as unknown as Mock;

const LINK = (id: string, title: string, sort_order: number): BioLink => ({
  id, link_id: `k${id}`, title, destination: `https://dest.test/${id}`, icon: "", icon_stock: null, icon_url: "",
  background_image: "", background_url: "", is_adult: false, mode: "", tracking: false, default_tracking_code: "",
  geo: null, sort_order, updated_at: "2026-11-11T00:00:00Z",
});
let page: BioPage;

beforeEach(() => {
  push.mockReset();
  page = {
    profile: {
      id: "p1", username: "alice", display_name: "Alice", bio: "", avatar: "", avatar_url: "", background_url: "", account_id: null,
      mode: "escape_ig", verified: false, custom_domain: { domain: "alice.example", status: "live" },
      public_url: "https://bio.test/alice", created_at: "2026-11-11T00:00:00Z", updated_at: "2026-11-11T00:00:00Z",
    },
    links: [LINK("a", "First", 0), LINK("b", "Second", 1)],
  };
  relayGet.mockImplementation((path: string) => {
    if (path === "/admin/bio-pages/p1") return Promise.resolve(page);
    if (path === "/admin/accounts") return Promise.resolve({ accounts: [] });
    return new Promise(() => {});
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const titles = (sel: string) => [...document.querySelectorAll(sel)].map((e) => e.getAttribute(sel.slice(1, -1)));
const preview = () => within(screen.getByRole("region", { name: "Preview" }));

describe("BioEditor", () => {
  it("saves a Display name edit as the only change; the preview follows the draft", async () => {
    renderWithProviders(<BioEditor profileId="p1" />);
    const name = await screen.findByLabelText(/Display name/);
    await waitFor(() => expect((name as HTMLInputElement).value).toBe("Alice"));
    expect(document.querySelector("[data-custom-domain]")?.textContent).toBe("alice.example · live");
    fireEvent.change(name, { target: { value: "Alice B" } });
    expect(preview().getByRole("heading", { name: "Alice B" })).toBeTruthy();
    relayPatch.mockResolvedValueOnce({ ...page, profile: { ...page.profile, display_name: "Alice B" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved")).toBeTruthy();
    expect(relayPatch).toHaveBeenCalledWith("/admin/bio-pages/p1", { display_name: "Alice B" });
  });

  it("adds a link through the dialog and moves a link up with every id in the new order", async () => {
    renderWithProviders(<BioEditor profileId="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Add link" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Add link" }));
    fireEvent.change(dialog.getByLabelText(/Title/), { target: { value: "Third" } });
    fireEvent.change(dialog.getByLabelText(/Destination/), { target: { value: "https://dest.test/c" } });
    expect(titles("[data-preview-link]")).toEqual(["First", "Second", "Third"]);
    relayPost.mockResolvedValueOnce({ ...page, links: [...page.links, LINK("c", "Third", 2)] });
    fireEvent.click(dialog.getByRole("button", { name: "Save link" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(relayPost).toHaveBeenCalledWith("/admin/bio-pages/p1/links",
      expect.objectContaining({ title: "Third", destination: "https://dest.test/c" }));
    expect(titles("[data-bio-link]")).toEqual(["First", "Second", "Third"]);

    relayPut.mockResolvedValueOnce({ ...page, links: [LINK("a", "First", 0), LINK("c", "Third", 1), LINK("b", "Second", 2)] });
    fireEvent.click(screen.getByRole("button", { name: "Move Third up" }));
    await waitFor(() => expect(titles("[data-bio-link]")).toEqual(["First", "Third", "Second"]));
    expect(relayPut).toHaveBeenCalledWith("/admin/bio-pages/p1/links/order", { ids: ["a", "c", "b"] });
    expect(titles("[data-preview-link]")).toEqual(["First", "Third", "Second"]);
  });

  it("uploads a new background to the last unknown link in a stale page response", async () => {
    renderWithProviders(<BioEditor profileId="p1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Add link" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Add link" }));
    fireEvent.change(dialog.getByLabelText(/Title/), { target: { value: "Mine" } });
    fireEvent.change(dialog.getByLabelText(/Destination/), { target: { value: "https://dest.test/mine" } });
    const file = new File(["image"], "background.png", { type: "image/png" });
    fireEvent.change(dialog.getByLabelText(/Background image/), { target: { files: [file] } });
    relayPost.mockResolvedValueOnce({ ...page, links: [...page.links, LINK("other", "Other tab", 2), LINK("mine", "Mine", 3)] });
    relayUpload.mockResolvedValueOnce({ ...page, links: [...page.links, LINK("other", "Other tab", 2), LINK("mine", "Mine", 3)] });
    fireEvent.click(dialog.getByRole("button", { name: "Save link" }));
    await waitFor(() => expect(relayUpload).toHaveBeenCalledWith(
      "/admin/bio-pages/p1/links/mine/background", file));
  });

  it("uploads the page background, then removes it", async () => {
    const relayDelete = relay.delete as unknown as Mock;
    renderWithProviders(<BioEditor profileId="p1" />);
    const row = within((await screen.findByRole("button", { name: "Upload background" })).closest("[data-bio-background]") as HTMLElement);
    expect(row.queryByRole("button", { name: "Remove" })).toBeNull();
    const file = new File(["image"], "bg.png", { type: "image/png" });
    relayUpload.mockResolvedValueOnce({ ...page, profile: { ...page.profile, background_url: "/f/bg.webp" } });
    fireEvent.change(row.getByLabelText("Background image"), { target: { files: [file] } });
    await waitFor(() => expect(row.getByRole("button", { name: "Change background" })).toBeTruthy());
    expect(relayUpload).toHaveBeenCalledWith("/admin/bio-pages/p1/background", file);
    const shown = () => (screen.getByRole("region", { name: "Preview" }) as HTMLElement).style.backgroundImage;
    expect(shown()).toContain('url("/f/bg.webp")');
    relayDelete.mockResolvedValueOnce(page);
    fireEvent.click(row.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(row.getByRole("button", { name: "Upload background" })).toBeTruthy());
    expect(shown()).toBe("");
    expect(relayDelete).toHaveBeenCalledWith("/admin/bio-pages/p1/background");
  });

  it("says an unknown page doesn't exist", async () => {
    relayGet.mockImplementation(() => Promise.reject(new RelayError(404, { detail: "Not Found" })));
    renderWithProviders(<BioEditor profileId="p1" />);
    expect(await screen.findByText("This bio page doesn't exist.")).toBeTruthy();
  });

  it("evicts a cached page after a 404 refetch and removes its editor", async () => {
    const client = makeTestQueryClient();
    client.setQueryData(["bio-pages", "p1"], page);
    relayGet.mockImplementation((path: string) => path === "/admin/bio-pages/p1"
      ? Promise.reject(new RelayError(404, { detail: "Not Found" }))
      : Promise.resolve({ accounts: [] }));
    renderWithProviders(<BioEditor profileId="p1" />, client);
    expect(await screen.findByText("This bio page doesn't exist.")).toBeTruthy();
    expect(screen.queryByLabelText(/Display name/)).toBeNull();
    await waitFor(() => expect(client.getQueryData(["bio-pages", "p1"])).toBeUndefined());
  });
});
