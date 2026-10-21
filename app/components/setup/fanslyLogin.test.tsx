/**
 * The Fansly sign-in against Infloww's (`FanslyLogin`, index.9f50f370.js @12411710): Done beside Cancel, its error
 * wording (creators0187 / creators0310 / creators0416), the linked account as fansly.com/username with its avatar,
 * an expired session's row (fansly0003, relink at the Fansly paste step), and one Fansly account per Creator
 * (creators0408). The Relay client is mocked; fixture ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";

vi.mock("@/lib/relay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/relay")>()),
  relay: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import AccountsTable from "@/components/setup/AccountsTable";
import AddCreatorModal from "@/components/setup/AddCreatorModal";
import { FANSLY_T } from "@/components/setup/FanslyPasteSessionCard";
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
    expect(within(dialog()).getAllByRole("button").filter((b) => b.closest(".border-t")).map((b) => b.textContent))
      .toEqual(["Cancel", "Done"]);
    // The card draws no submit of its own inside the flow.
    expect(within(dialog()).queryByRole("button", { name: "Connect Fansly account" })).toBeNull();

    fireEvent.change(within(dialog()).getAllByRole("textbox")[0], { target: { value: BLOB } });
    fireEvent.click(btn("Done"));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/session/fansly", expect.objectContaining({ token: "tok", accountId: "fy-1", user_agent: "UA" })));

    // Linked: the avatar and fansly.com/username, not the raw id.
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

  it("a relay refusal reads creators0187, with the relay's answer below", async () => {
    relayPost.mockRejectedValue(new RelayError(400, { detail: "bad session" }));
    renderWithProviders(<AddCreatorModal extInstalled={null} at="fansly" onClose={() => {}} />);
    fireEvent.change(within(dialog()).getAllByRole("textbox")[0], { target: { value: BLOB } });
    fireEvent.click(btn("Done"));
    const out = await within(dialog()).findByText(new RegExp(FANSLY_T.loginFailed.replace(".", "\\.")));
    expect(out).toHaveTextContent("bad session");
  });

  it("a failed account-info read on the linked step reads creators0416", async () => {
    me = () => Promise.reject(new RelayError(502, null));
    relayPost.mockResolvedValue({ ok: true, account_id: "fy-1", platform: "fansly", name: null });
    renderWithProviders(<AddCreatorModal extInstalled={null} at="fansly" onClose={() => {}} />);
    fireEvent.change(within(dialog()).getAllByRole("textbox")[0], { target: { value: BLOB } });
    fireEvent.click(btn("Done"));
    expect(await within(dialog()).findByText(FANSLY_T.accountInfoError)).toBeInTheDocument();
  });

  it("greys out Fansly at the platform step once the Creator has a Fansly account (creators0408)", () => {
    renderWithProviders(
      <AddCreatorModal extInstalled={null} onClose={() => {}} linkAnother={{ creator: { name: "Fiona", gender: "" }, linked: ["fansly"] }} />,
    );
    const fansly = within(dialog()).getByLabelText("Fansly");
    expect(fansly).toBeDisabled();
    expect(fansly.closest("label")).toHaveAttribute("title", expect.stringContaining("Fansly"));
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
    expect(onLink).toHaveBeenLastCalledWith("fansly");

    fireEvent.click(screen.getByRole("button", { name: "More actions for Fiona" }));
    expect(screen.queryByRole("group", { name: "Recovery" })).toBeNull();
  });

  it("an OnlyFans row keeps its own relink and recovery", async () => {
    accounts = [{ id: "of-1", nickname: "Oscar", platform: "onlyfans", has_session: true }];
    health = [{ account_id: "of-1", ok: false, error: "auth failed" }];
    const onLink = vi.fn();
    renderWithProviders(<AccountsTable onLink={onLink} />);
    expect(await screen.findByTitle("auth failed")).toHaveTextContent("Disconnected");
    fireEvent.click(screen.getByRole("button", { name: "Link creator account" }));
    expect(onLink).toHaveBeenLastCalledWith("paste");
    fireEvent.click(screen.getByRole("button", { name: "More actions for Oscar" }));
    expect(screen.getByRole("group", { name: "Recovery" })).toBeInTheDocument();
  });
});
