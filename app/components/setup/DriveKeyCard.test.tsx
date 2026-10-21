/**
 * The Drive key on Settings → AI keys. A master edits the server's
 * GOOGLE_DRIVE_API_KEY through the same masked /admin/secrets store as the
 * "Server keys" card: the raw value never comes back, a blank field keeps it,
 * and clear sends "". Anyone else gets a line and no master-only read.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

let session: { user: { is_admin?: boolean } | null } = { user: null };
vi.mock("@/contexts/UserContext", () => ({ useUser: () => session }));
vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), put: vi.fn() } }));

import DriveKeyCard from "./DriveKeyCard";
import { relay } from "@/lib/relay";

const get = relay.get as unknown as Mock;
const put = relay.put as unknown as Mock;

const status = (set: boolean) => ({
  keys: {
    GOOGLE_DRIVE_API_KEY: {
      label: "Google Drive API key", group: "Vault import", secret: true, multiline: false,
      help: "Lets the vault importer pull publicly-shared Drive links.", set, clearable: set,
      source: set ? "store" : "unset", hint: set ? "AIza…wxyz" : "",
    },
    OTHER_KEY: {
      label: "Other", group: "x", secret: true, multiline: false, help: "", set: true,
      clearable: true, source: "store", hint: "sk-…",
    },
  },
});

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DriveKeyCard />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  put.mockReset();
});
afterEach(() => cleanup());

describe("DriveKeyCard", () => {
  it("for a master, shows only the Drive key, masked, and saves just that field", async () => {
    session = { user: { is_admin: true } };
    get.mockResolvedValue(status(false));
    put.mockResolvedValue(status(true));
    const user = userEvent.setup();
    renderCard();

    const field = await screen.findByLabelText("Google Drive API key");
    expect(field.getAttribute("type")).toBe("password");
    expect(screen.queryByText("Other")).toBeNull();
    expect(screen.getByText("not set")).toBeInTheDocument();
    expect(screen.getByText(/Anyone with the link can view/)).toBeInTheDocument();

    await user.type(field, "AIza-placeholder");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/admin/secrets", { GOOGLE_DRIVE_API_KEY: "AIza-placeholder" }));
    // The saved key reads back masked, never as typed.
    expect(await screen.findByText(/set · via UI/)).toBeInTheDocument();
    expect(screen.getByLabelText("Google Drive API key")).toHaveValue("");
    expect(screen.getByLabelText("Google Drive API key").getAttribute("placeholder")).toContain("AIza…wxyz");
  });

  it("clear sends an empty value for the Drive key alone", async () => {
    session = { user: { is_admin: true } };
    get.mockResolvedValue(status(true));
    put.mockResolvedValue(status(false));
    const user = userEvent.setup();
    renderCard();

    await user.click(await screen.findByRole("button", { name: "clear" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/admin/secrets", { GOOGLE_DRIVE_API_KEY: "" }));
  });

  it("for anyone else, says who sets it and never reads the master-only store", async () => {
    session = { user: { is_admin: false } };
    renderCard();
    expect(screen.getByText(/its owner sets it here/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Google Drive API key")).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });
});
