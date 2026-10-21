/**
 * The S4S settings page (docs/spec/phase-03-share-for-share.md, Testing Decisions, seam 2; page-parity 15), for one
 * creator, rendered with the relay mocked at `fetch` by URL, so every save assertion is an assertion about the wire.
 * Fixture names and ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import S4SSettingPanel, { PARTNER_PROFILE_LINE } from "@/components/s4s/S4SSettingPanel";
import { useS4SProfiles, type S4SProfile, type S4SProfiles } from "@/lib/s4s";

/** The vault picker stubbed to a list of the ids it was opened with and one confirm of `pick.ids`. */
const pick = vi.hoisted(() => ({ ids: [] as number[] }));
vi.mock("@/components/chat/VaultPicker", () => ({
  VaultPicker: ({ open, initialSelectedIds, onConfirm }: {
    open: boolean; initialSelectedIds: number[]; onConfirm: (picked: { id: number }[]) => void;
  }) => open ? (
    <div>
      <span>{`picked: ${initialSelectedIds.join(",")}`}</span>
      <button type="button" onClick={() => onConfirm(pick.ids.map((id) => ({ id })))}>Confirm pick</button>
    </div>
  ) : null,
}));

type Call = { method: string; url: string; body: unknown };

const FRESH: S4SProfile = {
  account_id: "7000001", profile_id: null, opted_in: false, discovery_visible: true, daily_limit: 1,
  display_name: "fixture_one", username: "fixture_one", avatar_url: null, posts: [],
};
const SAVED: S4SProfile = {
  account_id: "7000002", profile_id: 4, opted_in: true, discovery_visible: true, daily_limit: 2,
  display_name: "Fixture Two", username: "fixture_two", avatar_url: null,
  posts: [
    { id: 11, caption: "Promo eleven", is_primary: true, media: [{ id: 70, vault_media_id: 501, media_type: "photo" }] },
    { id: 12, caption: "Promo twelve", is_primary: false, media: [] },
  ],
};

let fetchMock: ReturnType<typeof vi.fn>;
let profiles: S4SProfiles;

function calls(): Call[] {
  return fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}
const writes = () => calls().filter((c) => c.method !== "GET");

beforeEach(() => {
  profiles = { live_posting: false, profiles: [FRESH, SAVED] };
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (url === "/admin/s4s/profiles" && method === "GET") return jsonRes(profiles);
    if (url === "/admin/s4s/profiles/7000001" && method === "PUT") return jsonRes({ ...FRESH, profile_id: 9, ...body });
    if (url === "/admin/s4s/profiles/7000001/posts" && method === "POST") {
      return jsonRes({ id: 30, caption: body.caption, is_primary: true, media: [] });
    }
    if (url === "/admin/s4s/profiles/7000001/posts/30/media" && method === "PUT") {
      return jsonRes(body.vault_media_ids.map((v: number, i: number) => ({ id: 80 + i, vault_media_id: v, media_type: "photo" })));
    }
    if (url.startsWith("/admin/s4s/profiles/7000002/posts/")) {
      if (method === "DELETE") return jsonRes({ deleted: 12 });
      return jsonRes({ id: 12, caption: body?.caption ?? "Promo twelve", is_primary: url.endsWith("/primary") });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** The page as S4SPage mounts it: the profiles query, and the rail's creator. */
function Harness({ id }: { id: string }) {
  const q = useS4SProfiles();
  return <S4SSettingPanel query={q} profile={q.data?.profiles.find((p) => p.account_id === id) ?? null} />;
}

async function mount(id: string, name: string) {
  renderWithProviders(<Harness id={id} />);
  return screen.findByRole("region", { name: `S4S settings for ${name}` });
}

describe("S4SSettingPanel", () => {
  it("shows one creator: Create post, its limit, and the switches; nothing is written", async () => {
    const page = await mount("7000001", "fixture_one");
    expect(screen.queryByRole("region", { name: /Fixture Two/ })).toBeNull();
    expect(within(page).getByRole("heading", { name: "Primary post" })).toBeInTheDocument();
    expect(within(page).getByRole("button", { name: "Create post" })).toBeInTheDocument();
    expect(within(page).getByText("This post will be used for all Share for Share requests")).toBeInTheDocument();
    expect(within(page).getByText("per day")).toHaveClass("text-[#ff7c71]");
    expect(within(page).getByRole("combobox", { name: "Limit daily S4S" })).toHaveTextContent("1 Share for Share");
    expect(within(page).getByRole("switch", { name: "Take part in Share for Share" })).toHaveAttribute("aria-checked", "false");
    expect(within(page).getByRole("switch", { name: "Appear on Discover Creators" })).toHaveAttribute("aria-checked", "true");
    expect(within(page).getByText("Allow fixture_one to appear on the Discover Creators page")).toBeInTheDocument();
    expect(writes()).toEqual([]);
  });

  it("shows the primary caption with its tag", async () => {
    const page = await mount("7000002", "Fixture Two");
    expect(within(page).getByText("Promo eleven")).toBeInTheDocument();
    expect(within(page).getByText("Primary")).toBeInTheDocument();
    expect(within(page).queryByRole("button", { name: "Create post" })).toBeNull();
  });

  it("Limit daily S4S saves daily_limit only", async () => {
    const page = await mount("7000001", "fixture_one");
    const save = within(page).getAllByRole("button", { name: "Save" })[0];
    expect(save).toBeDisabled();
    fireEvent.click(within(page).getByRole("combobox", { name: "Limit daily S4S" }));
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "3 Share for Shares" }));
    fireEvent.click(save);
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({ method: "PUT", url: "/admin/s4s/profiles/7000001", body: { daily_limit: 3 } });
  });

  it("the switches save on toggle", async () => {
    const page = await mount("7000001", "fixture_one");
    fireEvent.click(within(page).getByRole("switch", { name: "Take part in Share for Share" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({ method: "PUT", url: "/admin/s4s/profiles/7000001", body: { opted_in: true } });
    await waitFor(() => expect(within(page).getByRole("switch", { name: "Appear on Discover Creators" })).toBeEnabled());
    fireEvent.click(within(page).getByRole("switch", { name: "Appear on Discover Creators" }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()[1]).toEqual({ method: "PUT", url: "/admin/s4s/profiles/7000001", body: { discovery_visible: false } });
  });

  it("Profile shown to partners is the creator's OnlyFans profile, read only", async () => {
    profiles = {
      live_posting: false,
      profiles: [{ ...FRESH, display_name: "Fixture One OF", username: "fixture_one_of",
        avatar_url: "https://thumbs.onlyfans.com/public/files/thumbs/c144/one/avatar.jpg" }],
    };
    const page = await mount("7000001", "Fixture One OF");
    const shown = within(page).getByRole("group", { name: "Profile shown to partners" });
    expect(within(shown).getByText("Fixture One OF")).toBeInTheDocument();
    expect(within(shown).getByText("@fixture_one_of")).toBeInTheDocument();
    expect(within(shown).getByRole("img", { name: "Fixture One OF" })).toHaveAttribute(
      "src", "https://thumbs.onlyfans.com/public/files/thumbs/c144/one/avatar.jpg");
    for (const label of ["Display name", "@username", "Avatar URL"]) expect(within(page).queryByLabelText(label)).toBeNull();
    expect(within(page).getByText(PARTNER_PROFILE_LINE)).toBeInTheDocument();
    // Only Limit daily S4S has a Save left on the page.
    expect(within(page).getAllByRole("button", { name: "Save" })).toHaveLength(1);
  });

  it("Create post opens the pop-up", async () => {
    const page = await mount("7000001", "fixture_one");
    fireEvent.click(within(page).getByRole("button", { name: "Create post" }));
    const dialog = screen.getByRole("dialog", { name: "Create post" });
    const caption = within(dialog).getByLabelText("Caption");
    expect(caption).toHaveAttribute("maxLength", "5000");
    fireEvent.change(caption, { target: { value: "A brand new promo" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({ method: "POST", url: "/admin/s4s/profiles/7000001/posts", body: { caption: "A brand new promo" } });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("Create post attaches up to 5 vault items, saved to the new post after it is made", async () => {
    const page = await mount("7000001", "fixture_one");
    fireEvent.click(within(page).getByRole("button", { name: "Create post" }));
    fireEvent.change(within(screen.getByRole("dialog", { name: "Create post" })).getByLabelText("Caption"),
      { target: { value: "Promo with media" } });

    pick.ids = [601, 602, 603, 604, 605, 606];
    fireEvent.click(within(screen.getByRole("dialog", { name: "Create post" })).getByRole("button", { name: "Add from Vault (0/5)" }));
    // The picker stands in for the pop-up while it is open.
    expect(screen.queryByRole("dialog", { name: "Create post" })).toBeNull();
    expect(screen.getByText("picked:")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm pick" }));
    let dialog = screen.getByRole("dialog", { name: "Create post" });
    expect(within(dialog).getByRole("alert")).toHaveTextContent("at most 5 media; you picked 6");
    expect(within(dialog).getByRole("button", { name: "Add from Vault (0/5)" })).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Caption")).toHaveValue("Promo with media");

    pick.ids = [601, 602];
    fireEvent.click(within(dialog).getByRole("button", { name: "Add from Vault (0/5)" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm pick" }));
    dialog = screen.getByRole("dialog", { name: "Create post" });
    expect(within(dialog).queryByRole("alert")).toBeNull();
    expect(within(dialog).getAllByRole("img", { name: "Picked vault media" })).toHaveLength(2);
    expect(within(dialog).getByRole("button", { name: "Add from Vault (2/5)" })).toBeInTheDocument();
    expect(writes()).toEqual([]);

    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()).toEqual([
      { method: "POST", url: "/admin/s4s/profiles/7000001/posts", body: { caption: "Promo with media" } },
      { method: "PUT", url: "/admin/s4s/profiles/7000001/posts/30/media", body: { vault_media_ids: [601, 602] } },
    ]);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("Manage posts moves the Primary mark, edits and deletes a post", async () => {
    const page = await mount("7000002", "Fixture Two");
    fireEvent.click(within(page).getByRole("button", { name: "Manage posts" }));
    const manage = screen.getByRole("region", { name: "Manage posts" });
    expect(within(manage).getByText("2 / 20 S4S posts")).toBeInTheDocument();
    const row = within(manage).getByText("Promo twelve").closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Set as Primary Post" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toMatchObject({ method: "POST", url: "/admin/s4s/profiles/7000002/posts/12/primary" });

    await waitFor(() => expect(within(row).getByRole("button", { name: "Edit" })).toBeEnabled());
    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Post" });
    expect(within(dialog).getByLabelText("Caption")).toHaveValue("Promo twelve");
    fireEvent.change(within(dialog).getByLabelText("Caption"), { target: { value: "Promo twelve, edited" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(writes()).toHaveLength(2));
    expect(writes()[1]).toEqual({ method: "PATCH", url: "/admin/s4s/profiles/7000002/posts/12", body: { caption: "Promo twelve, edited" } });

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(within(within(manage).getByText("Promo twelve").closest("tr")!).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(writes()).toHaveLength(3));
    expect(writes()[2]).toMatchObject({ method: "DELETE", url: "/admin/s4s/profiles/7000002/posts/12" });

    fireEvent.click(within(manage).getByRole("button", { name: "Back" }));
    expect(screen.getByRole("region", { name: "S4S settings for Fixture Two" })).toBeInTheDocument();
  });

  it("Manage posts sets a post's media from the vault, at most 5, showing the Relay's copies", async () => {
    const page = await mount("7000002", "Fixture Two");
    expect(within(page).getByRole("img", { name: "S4S photo" })).toHaveAttribute("src", "/admin/s4s/media/70");
    fireEvent.click(within(page).getByRole("button", { name: "Manage posts" }));
    const manage = screen.getByRole("region", { name: "Manage posts" });
    const row = within(manage).getByText("Promo eleven").closest("tr")!;
    expect(within(row).getByRole("img", { name: "S4S photo" })).toHaveAttribute("src", "/admin/s4s/media/70");
    pick.ids = [501, 502, 503, 504, 505, 506];
    fireEvent.click(within(row).getByRole("button", { name: "Add from Vault (1/5)" }));
    expect(within(manage).getByText("picked: 501")).toBeInTheDocument();
    fireEvent.click(within(manage).getByRole("button", { name: "Confirm pick" }));
    expect(within(manage).getByRole("alert")).toHaveTextContent("at most 5 media; you picked 6");
    expect(writes()).toEqual([]);
    pick.ids = [501, 502];
    fireEvent.click(within(row).getByRole("button", { name: "Add from Vault (1/5)" }));
    fireEvent.click(within(manage).getByRole("button", { name: "Confirm pick" }));
    await waitFor(() => expect(writes()).toHaveLength(1));
    expect(writes()[0]).toEqual({
      method: "PUT", url: "/admin/s4s/profiles/7000002/posts/11/media", body: { vault_media_ids: [501, 502] },
    });
  });

  it("offers no Create post once a creator holds 20 posts", async () => {
    const posts = Array.from({ length: 20 }, (_, i) => ({ id: 100 + i, caption: `Promo ${i}`, is_primary: i === 0, media: [] }));
    profiles = { live_posting: false, profiles: [{ ...FRESH, posts }] };
    const page = await mount("7000001", "fixture_one");
    fireEvent.click(within(page).getByRole("button", { name: "Manage posts" }));
    const manage = screen.getByRole("region", { name: "Manage posts" });
    expect(within(manage).getByRole("button", { name: "Create post" })).toBeDisabled();
    expect(within(manage).getByText("20 / 20 S4S posts")).toBeInTheDocument();
  });

  it("shows the relay's refusal when opting in fails", async () => {
    const detail = "set a display name and @username before opting in: this Creator has no nickname to prefill them";
    const base = fetchMock.getMockImplementation() as (url: string, init?: RequestInit) => Promise<Response>;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) =>
      url === "/admin/s4s/profiles/7000001" && init?.method === "PUT" ? jsonRes({ detail }, 400) : base(url, init));
    const page = await mount("7000001", "fixture_one");
    fireEvent.click(within(page).getByRole("switch", { name: "Take part in Share for Share" }));
    expect(await within(page).findByRole("alert")).toHaveTextContent(`Couldn't save: ${detail}`);
  });

  it("says so when no creator is picked", async () => {
    profiles = { live_posting: false, profiles: [] };
    renderWithProviders(<Harness id="7000001" />);
    expect(await screen.findByText("No creator connected yet")).toBeInTheDocument();
  });
});
