/**
 * YourAccountTab — the Your Account Panel (docs/spec/settings-tabs/phase-01-account-preferences.md).
 *
 * Rendered inside `UserProvider`, with the relay mocked at `fetch` by URL: the
 * same stub serves `/auth/me` (the signed-in username) and the `account`
 * Settings blob, so every save assertion is an assertion about the wire.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

import { jsonRes, renderWithProviders } from "@/test-utils";
import { UserProvider } from "@/contexts/UserContext";
import YourAccountTab from "@/components/settings/YourAccountTab";
import { avatarDataUrl } from "@/lib/creatorProfiles";

// jsdom has no canvas: the picture's resize is stubbed to a fixed data URL.
const PIC = "data:image/jpeg;base64,AAAA";
vi.mock("@/lib/creatorProfiles", () => ({ avatarDataUrl: vi.fn(async () => PIC) }));

type Call = { method: string; url: string; body: unknown };

let fetchMock: ReturnType<typeof vi.fn>;
/** What GET /admin/settings/account answers. */
let getReply: () => Response;

function calls(): Call[] {
  return fetchMock.mock.calls.map(([url, init]) => ({
    method: (init?.method ?? "GET") as string,
    url: String(url),
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}
const puts = () => calls().filter((c) => c.method === "PUT");

beforeEach(() => {
  localStorage.clear();
  getReply = () => jsonRes({ tab: "account", config: {} });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/auth/me") return jsonRes({ user_id: "u1", username: "alphaone" });
    if (url === "/admin/settings/account" && method === "GET") return getReply();
    if (url === "/admin/settings/account" && method === "PUT") {
      return jsonRes({ tab: "account", config: JSON.parse(String(init?.body)) });
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

function mount() {
  return renderWithProviders(
    <UserProvider>
      <YourAccountTab />
    </UserProvider>,
  );
}

const save = () => screen.getByRole("button", { name: /save/i });

describe("YourAccountTab", () => {
  it("shows the signed-in username read-only and as the Personal picture's initials", async () => {
    mount();
    const username = screen.getByLabelText("Username");
    await waitFor(() => expect(username).toHaveValue("alphaone"));
    expect(username).toHaveAttribute("readonly");
    expect(screen.getByRole("img", { name: "Personal picture" })).toHaveTextContent(/^A$/);
    expect(screen.getByText("Personal")).toBeInTheDocument();
    expect(screen.getByText("Agency info")).toBeInTheDocument();
  });

  it("renders Edit and the Personal picture's camera veil disabled with \"not wired\"; the Agency one is live", async () => {
    mount();
    const edit = screen.getByRole("button", { name: "Edit" });
    expect(edit).toBeDisabled();
    expect(edit).toHaveAttribute("title", "not wired");
    expect(screen.queryByRole("button", { name: "Upload" })).toBeNull();
    const personal = screen.getByRole("button", { name: "Upload picture (not wired)" });
    expect(personal).toBeDisabled();
    expect(personal).toHaveAttribute("title", "not wired");
    expect(screen.getByRole("button", { name: "Upload Agency picture" })).toBeEnabled();
  });

  it("saves an uploaded Agency picture as a data URL and shows it", async () => {
    mount();
    await waitFor(() => expect(save()).toBeEnabled());
    const file = new File(["x"], "logo.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Agency picture file"), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByRole("img", { name: "Agency picture" }).querySelector("img")).toHaveAttribute("src", PIC));
    expect(avatarDataUrl).toHaveBeenCalledWith(file, 96);
    fireEvent.click(save());
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ agency_name: "", agency_picture: PIC });
  });

  it("says so when the picked file is not an image", async () => {
    vi.mocked(avatarDataUrl).mockRejectedValueOnce(new Error("not an image"));
    mount();
    await waitFor(() => expect(save()).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Agency picture file"), { target: { files: [new File(["x"], "a.txt")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("not an image");
  });

  it("saves and pre-fills the Telegram username", async () => {
    getReply = () => jsonRes({ tab: "account", config: { agency_name: "A", telegram_username: "@old" } });
    mount();
    const input = screen.getByLabelText("Telegram username (recommended)");
    await waitFor(() => expect(input).toHaveValue("@old"));
    fireEvent.change(input, { target: { value: "@new" } });
    fireEvent.click(save());
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ agency_name: "A", telegram_username: "@new" });
  });

  it("with an empty stored blob, saves exactly {agency_name} and shows its initials", async () => {
    mount();
    await waitFor(() => expect(save()).toBeEnabled());
    // Infloww's Save sits in the Panel header row, not after the body.
    expect(save().closest('[data-settings="panel-header"]')).not.toBeNull();
    fireEvent.change(screen.getByLabelText("Agency Name"), { target: { value: "Synthetic Agency" } });
    expect(screen.getByRole("img", { name: "Agency picture" })).toHaveTextContent(/^SA$/);
    fireEvent.click(save());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0]).toEqual({
      method: "PUT",
      url: "/admin/settings/account",
      body: { agency_name: "Synthetic Agency" },
    });
  });

  it("pre-fills a stored Agency Name", async () => {
    getReply = () => jsonRes({ tab: "account", config: { agency_name: "Beta Two" } });
    mount();
    await waitFor(() => expect(screen.getByLabelText("Agency Name")).toHaveValue("Beta Two"));
    expect(screen.getByRole("img", { name: "Agency picture" })).toHaveTextContent(/^BT$/);
  });

  it("keeps a stored key it does not show when it saves", async () => {
    getReply = () => jsonRes({ tab: "account", config: { agency_name: "Beta Two", extra: 1 } });
    mount();
    const input = screen.getByLabelText("Agency Name");
    await waitFor(() => expect(input).toHaveValue("Beta Two"));
    fireEvent.change(input, { target: { value: "Gamma Three" } });
    fireEvent.click(save());

    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(puts()[0].body).toEqual({ agency_name: "Gamma Three", extra: 1 });
  });

  it("a failed GET keeps Save disabled and sends no PUT (Load gate)", async () => {
    getReply = () => jsonRes({ detail: "boom" }, 500);
    mount();
    await waitFor(() => expect(screen.getByText(/never loaded/)).toBeInTheDocument());
    expect(save()).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Agency Name"), { target: { value: "Synthetic Agency" } });
    fireEvent.click(save());
    await new Promise((r) => setTimeout(r, 20));
    expect(puts()).toEqual([]);
  });

  it("never calls the Creator's OnlyFans profile and says it is not applied yet", async () => {
    mount();
    await waitFor(() => expect(save()).toBeEnabled());
    expect(screen.getByText("Saved for your organization; not applied yet.")).toBeInTheDocument();
    expect(calls().some((c) => c.url.includes("/api/of/v2/users/me"))).toBe(false);
  });
});
