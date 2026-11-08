/**
 * Two editors mounted at once (two Creators' pop-ups, two employee dialogs): each footer Save sits outside its form
 * (`form={id}`), so each form id must be its instance's own or the second Save submits the first form.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/relay")>();
  return { ...mod, relay: { ...mod.relay, get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/growth/smart-messages",
  useSearchParams: () => new URLSearchParams(),
}));

import PurchaseFollowupEditor from "@/components/growth/PurchaseFollowupEditor";
import LifecycleMessageEditor from "@/components/growth/LifecycleMessageEditor";
import { ResetPasswordModal } from "@/components/employees/EmployeeModals";
import { relay, type Employee } from "@/lib/relay";

const get = relay.get as unknown as Mock;
const put = relay.put as unknown as Mock;
const post = relay.post as unknown as Mock;
const EXTRAS = { media_ids: [], price_cents: 0, starts_at: null, ends_at: null, unsend_minutes: 0 };
const acc = (p: string) => new URLSearchParams(p.split("?")[1] ?? "").get("account_id") ?? "";

beforeEach(() => {
  get.mockImplementation((p: string) => {
    if (p.startsWith("/admin/purchase-followup-config")) {
      const defaults = { enabled: false, text: "Thanks", ...EXTRAS, frequency: "every", delay_range: [1, 3] };
      return Promise.resolve({ account_id: acc(p), defaults, config: defaults });
    }
    if (p.startsWith("/admin/lifecycle-message-config/buyers")) return Promise.resolve({ window_days: 7, buyers: [] });
    if (p.startsWith("/admin/lifecycle-message-config")) {
      const defaults = { enabled: false, text: "Happy birthday", hours: null, messages: [], ...EXTRAS, frequency: "once" };
      return Promise.resolve({ account_id: acc(p), kind: "birthday_message", defaults, config: defaults });
    }
    return Promise.resolve({});
  });
  put.mockResolvedValue({});
  post.mockResolvedValue({});
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const noop = () => {};

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

describe("two editors mounted at once each submit their own form", () => {
  it("Purchased: the second Save writes the second Creator", async () => {
    wrap(<><PurchaseFollowupEditor accountId="acc-1" onTouched={noop} /><PurchaseFollowupEditor accountId="acc-2" onTouched={noop} /></>);
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(2));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Save" })[1]); });
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put.mock.calls[0][1]).toMatchObject({ account_id: "acc-2" });
  });

  it("a lifecycle message: the second Save writes the second Creator", async () => {
    wrap(<><LifecycleMessageEditor accountId="acc-1" kind="birthday_message" onTouched={noop} />
      <LifecycleMessageEditor accountId="acc-2" kind="birthday_message" onTouched={noop} /></>);
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Save" })).toHaveLength(2));
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Save" })[1]); });
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put.mock.calls[0][1]).toMatchObject({ account_id: "acc-2" });
  });

  it("Reset password: the second dialog's button resets the second employee", async () => {
    const emp = (id: number) => ({ id, display_name: `Emp ${id}`, username: `emp${id}` }) as unknown as Employee;
    wrap(<><ResetPasswordModal employee={emp(1)} onClose={() => {}} /><ResetPasswordModal employee={emp(2)} onClose={() => {}} /></>);
    const pw = screen.getAllByLabelText(/^New password/);
    const again = screen.getAllByLabelText(/^Confirm password/);
    fireEvent.change(pw[1], { target: { value: "secret2" } });
    fireEvent.change(again[1], { target: { value: "secret2" } });
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Reset password" })[1]); });
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][0]).toBe("/admin/employees/2/password");
  });
});
