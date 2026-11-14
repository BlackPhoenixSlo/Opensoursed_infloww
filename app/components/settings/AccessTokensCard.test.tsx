/**
 * AccessTokensCard — Settings › AI keys › Access tokens: list with hint/expiry/last use, New token (name + expiry,
 * the token shown once with Copy, gone after Done), Revoke behind a confirm; revoked/expired rows have no Revoke.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));

import AccessTokensCard from "@/components/settings/AccessTokensCard";
import { relay } from "@/lib/relay";
import { renderWithProviders } from "@/test-utils";

const get = relay.get as unknown as Mock;
const post = relay.post as unknown as Mock;
const del = relay.delete as unknown as Mock;

const TOKEN = "ifw_" + "Q".repeat(43);
const FUTURE = "2099-01-01T00:00:00Z";
const row = (id: number, name: string, extra: Record<string, unknown> = {}) => ({
  id, name, hint: `ifw_…${String(id).padStart(4, "0")}`, created_at: "2026-11-14T00:00:00Z", expires_at: FUTURE,
  last_used_at: null, revoked_at: null, ...extra,
});

afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); del.mockReset(); vi.restoreAllMocks(); });

describe("AccessTokensCard", () => {
  it("lists tokens by hint; only active ones can be revoked", async () => {
    get.mockResolvedValue({ tokens: [
      row(1, "claude", { last_used_at: "2026-11-14T01:00:00Z" }),
      row(2, "old", { revoked_at: "2026-11-13T00:00:00Z" }),
      row(3, "lapsed", { expires_at: "2020-01-01T00:00:00Z" }),
    ] });
    renderWithProviders(<AccessTokensCard />);
    expect(await screen.findByText("ifw_…0001")).toBeInTheDocument();
    expect(screen.getByText("Revoked")).toBeInTheDocument();
    expect(screen.getByText("Expired")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Revoke" })).toHaveLength(1);
    expect(get).toHaveBeenCalledWith("/admin/owner-tokens");
  });

  it("creates with a trimmed name and 90 days, shows the token once, forgets it on Done", async () => {
    get.mockResolvedValue({ tokens: [] });
    post.mockResolvedValue({ ...row(9, "claude desktop"), token: TOKEN });
    renderWithProviders(<AccessTokensCard />);
    fireEvent.click(screen.getByRole("button", { name: "New token" }));
    const create = screen.getByRole("button", { name: "Create" }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "  claude desktop " } });
    expect(create.disabled).toBe(false);
    fireEvent.click(create);
    await waitFor(() => expect(post).toHaveBeenCalledWith("/admin/owner-tokens", { name: "claude desktop", days: 90 }));
    const shown = await screen.findByLabelText("Access token") as HTMLInputElement;
    expect(shown.value).toBe(TOKEN);
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("textbox", { name: "Access token" })).toBeNull();
    // The dialog's exit ghost (an aria-hidden copy) leaves within its fade; then the token is nowhere in the page.
    await waitFor(() => expect(screen.queryByDisplayValue(TOKEN)).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "New token" }));
    expect(screen.queryByDisplayValue(TOKEN)).toBeNull();
    expect((screen.getByLabelText("Name") as HTMLInputElement).value).toBe("");
  });

  it("revokes only after the confirm", async () => {
    get.mockResolvedValue({ tokens: [row(4, "claude")] });
    del.mockResolvedValue(row(4, "claude", { revoked_at: "2026-11-14T02:00:00Z" }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderWithProviders(<AccessTokensCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/admin/owner-tokens/4"));
  });
});
