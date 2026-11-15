/**
 * OfConsentCard — the "Auto-accept OnlyFans consent" checkbox: shown for every
 * Creator, a warning line above it while OF wants the consent form; one click PUTs
 * `{auto_accept}`; the line under it names who changed it and when.
 */
import { afterEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/contexts/UserContext", () => ({
  useUser: () => ({ user: { user_id: 1 } }),
}));
vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn() } };
});

import { OfConsentCard } from "@/components/settings/OfConsentCard";
import type { OfConsent } from "@/hooks/useOfConsent";
import { relay } from "@/lib/relay";

const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;

const view = (over: Partial<OfConsent>): OfConsent => ({
  account_id: "9", auto_accept: false, required: true, changed: null, ...over,
});

function mount(state: OfConsent) {
  let cur = state;
  relayGet.mockImplementation(async () => cur);
  relayPut.mockImplementation(async (_p: string, body: { auto_accept: boolean }) => {
    cur = { ...cur, auto_accept: body.auto_accept,
      changed: { enabled: body.auto_accept, user_id: "u", username: "boss", employee_id: 3,
        at: "2026-11-08T10:00:00Z" } };
    return cur;
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrap = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>);
  return render(<OfConsentCard accountId="9" />, { wrapper: wrap });
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("OfConsentCard", () => {
  it("shows for a Creator OF never flagged, off, with no warning", async () => {
    mount(view({ required: false }));
    const box = await screen.findByRole("checkbox", { name: "Auto-accept OnlyFans consent" });
    expect(box).not.toBeChecked();
    expect(screen.queryByTestId("consent-warn")).toBeNull();
    expect(screen.queryByTestId("consent-who")).toBeNull();
  });

  it("warns above the checkbox while OF wants the consent form", async () => {
    mount(view({}));
    const warn = await screen.findByTestId("consent-warn");
    expect(warn.textContent).toBe("OnlyFans is rejecting media sends: consent form needed");
    const box = screen.getByTestId("consent-box");
    expect(warn.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("one click turns it on, then names who and when", async () => {
    mount(view({}));
    const box = await screen.findByRole("checkbox", { name: "Auto-accept OnlyFans consent" });
    expect(box).not.toBeChecked();
    expect(screen.getByText(/onlyfans\.com\/my\/consent-form/)).toBeTruthy();
    fireEvent.click(box);
    await waitFor(() => expect(relayPut).toHaveBeenCalledWith("/admin/of-consent/9", { auto_accept: true }));
    await waitFor(() => expect(box).toBeChecked());
    expect(screen.getByTestId("consent-who").textContent).toMatch(/^Turned on by boss · /);
  });
});
