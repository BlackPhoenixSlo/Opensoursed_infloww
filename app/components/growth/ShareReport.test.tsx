/**
 * A share link's public report: the key from the URL, one read of `/share/<key>/data`, the links with their counts
 * and (when included) earnings; expired (410) and unknown (404) say so.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  usePathname: () => "/share/7.s3cret",
}));

import ShareReport from "@/components/growth/ShareReport";
import { renderWithProviders } from "@/test-utils";

const answer = (status: number, body: unknown = {}) =>
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(body), { status }));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("ShareReport", () => {
  it("reads the key's data once and draws the links, with earnings when included", async () => {
    const f = answer(200, {
      name: "For Bob", kind: "trial", include_earnings: true, updated_at: "2026-10-19T10:00:00Z",
      expires_at: "2026-10-26T10:00:00Z", ready: true,
      links: [{ name: "Reddit trial", created_at: null, claims: 2, clicks: 40, earnings_cents: 800, fans_who_spent: 1, fans_counted: 2 }],
    });
    renderWithProviders(<ShareReport />);
    expect(await screen.findByRole("heading", { name: "For Bob" })).toBeTruthy();
    expect(f).toHaveBeenCalledWith("/share/7.s3cret/data", expect.objectContaining({ credentials: "omit" }));
    const row = screen.getByText("Reddit trial").closest("tr")!;
    expect([...row.querySelectorAll("td")].map((td) => td.textContent)).toEqual(
      ["Reddit trial", "—", "2", "40", "$8.00", "1", "50.00%"]);
  });

  it("says when the link expired, and when it is unknown", async () => {
    answer(410);
    renderWithProviders(<ShareReport />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "This share link has expired" })).toBeTruthy());
    cleanup();
    answer(404);
    renderWithProviders(<ShareReport />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Share link not found" })).toBeTruthy());
  });
});
