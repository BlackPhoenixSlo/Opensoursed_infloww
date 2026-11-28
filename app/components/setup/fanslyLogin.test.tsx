import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";

vi.mock("@/lib/relay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/relay")>()),
  relay: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import AccountsTable from "@/components/setup/AccountsTable";
import AddCreatorModal from "@/components/setup/AddCreatorModal";
import { EditAccountModal } from "@/components/setup/EditCreatorModal";
import FanslyPasteSessionCard, { FANSLY_T } from "@/components/setup/FanslyPasteSessionCard";
import { relay, RelayError } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;

const BLOB = JSON.stringify({ platform: "fansly", token: "tok", id: "s1", accountId: "fy-1", device_id: "d1", user_agent: "UA" });
let me: () => Promise<unknown>;
let accounts: object[];
let health: object[];

beforeEach(() => {
  me = () => Promise.resolve({ id: "fy-1", name: "Fiona", username: "fiona", avatar: "https://cdn3.fansly.com/a.jpg" });
  accounts = [];
  health = [];
  relayGet.mockReset();
  relayGet.mockImplementation((path: string) => {
    if (path === "/api/of/v2/users/me") return me();
    if (path === "/admin/accounts") return Promise.resolve({ accounts, active_account_id: null });
    if (path === "/health?all_accounts=1") return Promise.resolve({ ok: true, accounts: health });
    return Promise.resolve({});
  });
  relayPost.mockReset();
});
afterEach(cleanup);

const dialog = () => screen.getByRole("dialog");
const btn = (name: string) => within(dialog()).getByRole("button", { name });

describe("Add creator, Fansly sign-in", () => {
  it("has Infloww's Done beside Cancel, and Done submits the pasted session", async () => {
    relayPost.mockResolvedValue({ ok: true, account_id: "fy-1", platform: "fansly", name: "Fiona" });
    renderWithProviders(<AddCreatorModal extInstalled={null} at="fansly" onClose={() => {}} />);
    expect(within(dialog().lastElementChild as HTMLElement).getAllByRole("button").map((b) => b.textContent))
      .toEqual(["Cancel", "Done"]);
    expect(within(dialog()).queryByRole("button", { name: "Connect Fansly account" })).toBeNull();

    fireEvent.change(within(dialog()).getAllByRole("textbox")[0], { target: { value: BLOB } });
    fireEvent.click(btn("Done"));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/session/fansly", expect.objectContaining({ token: "tok", accountId: "fy-1", user_agent: "UA" })));

    expect(await within(dialog()).findByText("fansly.com/fiona")).toBeInTheDocument();
    expect(within(dialog()).getByText("Fiona")).toBeInTheDocument();
    expect(dialog().querySelector('img[src="https://cdn3.fansly.com/a.jpg"]')).not.toBeNull();
    expect(within(dialog()).queryByText(FANSLY_T.accountInfoError)).toBeNull();
  });

  it("an empty or partial paste reads creators0310", async () => {
    renderWithProviders(<AddCreatorModal extInstalled={null} at="fansly" onClose={() => {}} />);
    fireEvent.click(btn("Done"));
    expect(await within(dialog()).findByText(new RegExp(FANSLY_T.mustLogIn))).toBeInTheDocument();
    fireEvent.change(within(dialog()).getAllByRole("textbox")[0], { target: { value: '{"token":"tok"}' } });
    fireEvent.click(btn("Done"));
    expect(await within(dialog()).findByText(/Missing token/)).toHaveTextContent(FANSLY_T.mustLogIn);
    expect(relayPost).not.toHaveBeenCalled();
  });

  it.each([
    [400, FANSLY_T.accountInfoError, "this session signs in as Fansly account fy-2, not fy-1"],
    [409, FANSLY_T.loginFailed, "fy-1 is already an onlyfans Creator"],
    [500, FANSLY_T.loginFailed, "boom"],
  ])("a relay %i reads its wording, with the relay's detail below", async (status, wording, detail) => {
    relayPost.mockRejectedValue(new RelayError(status, { detail }));
    renderWithProviders(<AddCreatorModal extInstalled={null} at="fansly" onClose={() => {}} />);
    fireEvent.change(within(dialog()).getAllByRole("textbox")[0], { target: { value: BLOB } });
    fireEvent.click(btn("Done"));
    const out = await within(dialog()).findByText((_, el) => el?.tagName === "PRE" && !!el.textContent?.startsWith(wording));
    expect(out).toHaveTextContent(`${status} FAILED`);
    expect(out).toHaveTextContent(detail);
  });

  it("a failed account-info read on the linked step reads creators0416", async () => {
    me = () => Promise.reject(new RelayError(502, null));
    relayPost.mockResolvedValue({ ok: true, account_id: "fy-1", platform: "fansly", name: null });
    renderWithProviders(<AddCreatorModal extInstalled={null} at="fansly" onClose={() => {}} />);
    fireEvent.change(within(dialog()).getAllByRole("textbox")[0], { target: { value: BLOB } });
    fireEvent.click(btn("Done"));
    expect(await within(dialog()).findByText(FANSLY_T.accountInfoError)).toBeInTheDocument();
  });

  it("Browser login signs in to Fansly through the remote login and links the account", async () => {
    relayPost.mockImplementation((path: string) => Promise.resolve(path === "/admin/login/remote/start"
      ? { id: "fj1", backend: "browserbase", state: "starting", message: "", error: null, account_id: null, session_file: null,
          proxy: "none", proxy_label: "", live_view_url: null, expires_at: 0 }
      : {}));
    relayGet.mockImplementation((path: string) => {
      if (path === "/api/of/v2/users/me") return me();
      if (path === "/admin/login/remote/fj1") {
        return Promise.resolve({ id: "fj1", backend: "browserbase", state: "done", message: "", error: null, account_id: "fy-1",
          session_file: "fansly_session.json", proxy: "none", proxy_label: "", live_view_url: null, expires_at: 0 });
      }
      if (path === "/admin/accounts") return Promise.resolve({ accounts, active_account_id: null });
      return Promise.resolve({});
    });
    renderWithProviders(<AddCreatorModal extInstalled={null} at="fanslyBrowser" expectedAccountId="fy-1" onClose={() => {}} />);
    const region = within(dialog()).getByRole("region", { name: "Fansly browser login" });
    expect(within(dialog()).queryByRole("region", { name: "Browserbase login" })).toBeNull();
    expect(within(dialog()).queryByRole("button", { name: "Done" })).toBeNull();
    fireEvent.change(within(region).getByLabelText("Fansly username or email"), { target: { value: "fiona" } });
    fireEvent.change(within(region).getByLabelText("Fansly password"), { target: { value: "pw" } });
    fireEvent.click(btn("Start browser login"));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/login/remote/start", expect.objectContaining({
      email: "fiona", platform: "fansly", backend: "browserbase", proxy: "none", expected_account_id: "fy-1",
    })));
    expect(await within(dialog()).findByText("fansly.com/fiona")).toBeInTheDocument();
  });

  it("locks switches at submit and unlocks after an immediate refusal", async () => {
    relayPost.mockRejectedValue(new RelayError(503, null, "offline"));
    renderWithProviders(
      <AddCreatorModal extInstalled={null} onClose={() => {}} linkAnother={{ creator: { name: "Fiona", gender: "" }, linked: [] }} />,
    );
    fireEvent.change(within(dialog()).getByLabelText("OnlyFans email"), { target: { value: "a@b.c" } });
    fireEvent.change(within(dialog()).getByLabelText("OnlyFans password"), { target: { value: "pw" } });
    expect(btn("Link a Fansly account instead")).toBeEnabled();
    fireEvent.click(btn("Start browser login"));
    expect(within(dialog()).queryByRole("button", { name: "Link a Fansly account instead" })).toBeNull();
    expect(await within(dialog()).findByText("Couldn't start the login: offline")).toBeInTheDocument();
    expect(await within(dialog()).findByRole("button", { name: "Link a Fansly account instead" })).toBeEnabled();
  });

  it("offers no Fansly sign-in once the Creator has a Fansly account (creators0408)", () => {
    renderWithProviders(
      <AddCreatorModal extInstalled={null} onClose={() => {}} linkAnother={{ creator: { name: "Fiona", gender: "" }, linked: ["fansly"] }} />,
    );
    expect(within(dialog()).getByRole("region", { name: "Browserbase login" })).toBeInTheDocument();
    expect(within(dialog()).queryByRole("button", { name: /Link a Fansly account/ })).toBeNull();
    expect(within(dialog()).queryByRole("region", { name: "Fansly paste session" })).toBeNull();
    expect(within(dialog()).queryByRole("region", { name: "Fansly browser login" })).toBeNull();
  });
});

describe("Fansly card", () => {
  const paste = (blob: string) => {
    fireEvent.change(screen.getAllByRole("textbox")[0], { target: { value: blob } });
    fireEvent.click(screen.getByRole("button", { name: "Connect Fansly account" }));
  };

  it("a success with name null shows the id and no account-info line", async () => {
    relayPost.mockResolvedValue({ ok: true, account_id: "fy-1", platform: "fansly", name: null });
    renderWithProviders(<FanslyPasteSessionCard />);
    paste(BLOB);
    expect(await screen.findByText(/Connected Fansly account fy-1/)).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(FANSLY_T.accountInfoError))).toBeNull();
  });

  it("a success with a name shows it", async () => {
    relayPost.mockResolvedValue({ ok: true, account_id: "fy-1", platform: "fansly", name: "Fiona" });
    renderWithProviders(<FanslyPasteSessionCard />);
    paste(BLOB);
    expect(await screen.findByText(/Connected Fansly account fy-1 \(Fiona\)/)).toBeInTheDocument();
  });

  it("with an expected id, a blob for another account is refused with no request", async () => {
    renderWithProviders(<FanslyPasteSessionCard expectedAccountId="fy-9" />);
    paste(BLOB);
    expect(await screen.findByText(/fy-1, not fy-9/)).toHaveTextContent(FANSLY_T.loginFailed);
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("with an expected id, a matching blob posts as today", async () => {
    relayPost.mockResolvedValue({ ok: true, account_id: "fy-1", platform: "fansly", name: "Fiona" });
    renderWithProviders(<FanslyPasteSessionCard expectedAccountId="fy-1" />);
    paste(BLOB);
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/session/fansly", expect.objectContaining({ accountId: "fy-1", token: "tok" })));
  });

  it("an 18-digit expected id matches the blob's exact id", async () => {
    relayPost.mockResolvedValue({ ok: true, account_id: "900539700124344320", platform: "fansly", name: null });
    renderWithProviders(<FanslyPasteSessionCard expectedAccountId="900539700124344320" />);
    paste('{"token":"tok","accountId":900539700124344320,"user_agent":"UA"}');
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/session/fansly", expect.objectContaining({ accountId: "900539700124344320" })));
  });

  it("a Fansly row's relink opens the modal whose card refuses another account's blob", async () => {
    renderWithProviders(<AddCreatorModal extInstalled={null} at="fansly" expectedAccountId="fy-9" onClose={() => {}} />);
    fireEvent.change(within(dialog()).getAllByRole("textbox")[0], { target: { value: BLOB } });
    fireEvent.click(btn("Done"));
    expect(await within(dialog()).findByText(/fy-1, not fy-9/)).toBeInTheDocument();
    expect(relayPost).not.toHaveBeenCalled();
  });
});

describe("Manage creators, an expired Fansly session", () => {
  it("reads Disconnected with fansly0003, relinks at the Fansly paste step, and offers no OnlyFans recovery", async () => {
    accounts = [{ id: "fy-1", nickname: "Fiona", platform: "fansly", has_session: true }];
    health = [{ account_id: "fy-1", ok: false, error: "fansly 401" }];
    const onLink = vi.fn();
    renderWithProviders(<AccountsTable onLink={onLink} />);
    expect(await screen.findByTitle(FANSLY_T.rebind)).toHaveTextContent("Disconnected");

    fireEvent.click(screen.getByRole("button", { name: "Link creator account" }));
    expect(onLink).toHaveBeenLastCalledWith("fansly", "fy-1");

    fireEvent.click(screen.getByRole("button", { name: "More actions for Fiona" }));
    expect(screen.queryByRole("group", { name: "Recovery" })).toBeNull();
  });

  it("Edit creator's Link on a disconnected Fansly account relinks with its id", () => {
    const onLink = vi.fn();
    renderWithProviders(
      <EditAccountModal account={{ id: "fy-1", nickname: "Fiona", platform: "fansly", has_session: true, is_active: true, proxy_down: false }} conn="Disconnected" onClose={() => {}} onLink={onLink} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Link account" }));
    expect(onLink).toHaveBeenLastCalledWith("fansly", "fy-1");
  });

  it("Edit creator on a disconnected OnlyFans account keeps its proxy box and relinks at Browserbase with no id", () => {
    const onLink = vi.fn();
    renderWithProviders(
      <EditAccountModal account={{ id: "of-1", nickname: "Oscar", platform: "onlyfans", has_session: true, is_active: true, proxy_down: false }} conn="Disconnected" onClose={() => {}} onLink={onLink} />,
    );
    expect(within(dialog()).getByText("OnlyFans")).toBeInTheDocument();
    expect(within(dialog()).getByText("Proxy connection")).toBeInTheDocument();
    expect(within(dialog()).queryByText(FANSLY_T.rebind)).toBeNull();
    const links = within(dialog()).getAllByRole("button", { name: "Link account" });
    expect(links).toHaveLength(2);
    for (const link of links) fireEvent.click(link);
    expect(onLink.mock.calls).toEqual([["browserbase"], ["browserbase"]]);
  });

  it("an OnlyFans row keeps its own relink and recovery", async () => {
    accounts = [{ id: "of-1", nickname: "Oscar", platform: "onlyfans", has_session: true }];
    health = [{ account_id: "of-1", ok: false, error: "auth failed" }];
    const onLink = vi.fn();
    renderWithProviders(<AccountsTable onLink={onLink} />);
    expect(await screen.findByTitle("auth failed")).toHaveTextContent("Disconnected");
    fireEvent.click(screen.getByRole("button", { name: "Link creator account" }));
    expect(onLink).toHaveBeenLastCalledWith("browserbase");
    fireEvent.click(screen.getByRole("button", { name: "More actions for Oscar" }));
    expect(screen.getByRole("group", { name: "Recovery" })).toBeInTheDocument();
  });
});
