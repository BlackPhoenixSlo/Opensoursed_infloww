/**
 * A page the chatter's Permission role denies, opened by URL, renders the
 * shell's denied-page panel in its place and never mounts, so it fires no
 * page query (docs/spec/phase-04-apply-stored-settings.md, story 34). The
 * page is a probe that fetches on mount; `fetch` is the mock that counts it.
 */
import { act, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AppliedSettings } from "@/lib/appliedSettings";
import { jsonRes, renderWithProviders } from "@/test-utils";

let pathname = "/";
let applied: { data?: AppliedSettings; isLoading?: boolean } = {};
let user: { username: string } | null = null;
vi.mock("next/navigation", () => ({ usePathname: () => pathname, useSearchParams: () => new URLSearchParams() }));
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user, logout: vi.fn() }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: { username: "fixture-chatter" } }) }));
vi.mock("@/components/shell/TopBar", () => ({ default: () => null }));
// The platform selector and gate read accounts and roster counts (PlatformSwitcher.test covers them).
vi.mock("@/components/shell/PlatformSwitcher", () => ({
  default: () => null,
  usePlatformUnread: () => ({ onlyfans: 0, fansly: 0 }),
  unreadLabel: String,
}));
vi.mock("@/components/shell/PlatformGate", () => ({ default: () => null, PlatformSync: () => null }));
// `realApplied` runs the real read (its query keyed by the Creator in scope)
// against `fetch`; otherwise the read is the `applied` stub.
let realApplied = false;
let scopeAccount: string | null = null;
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: scopeAccount }) }));
vi.mock("@/lib/appliedSettings", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/appliedSettings")>();
  return { ...actual, useAppliedSettings: () => (realApplied ? actual.useAppliedSettings() : applied) };
});

import AppShell from "@/components/shell/AppShell";

const fetchMock = vi.fn((_input?: RequestInfo | URL) => Promise.resolve(new Response("{}")));

function EmployeeReportsProbe() {
  useEffect(() => {
    void fetch("/admin/stats/per-employee");
  }, []);
  return <p>Employee reports page</p>;
}

const enforced = (pages: string[] | null): { data: AppliedSettings } => ({
  data: {
    preferences: { tz: null, report_tz: null, week_start: "monday" },
    messaging: { ai_translation: true },
    permissions: { enforced: true, pages, scope: "self" },
    flags: { fansly_manager: false },
  },
});

const renderShell = () =>
  render(
    <AppShell>
      <EmployeeReportsProbe />
    </AppShell>,
  );

beforeEach(() => {
  pathname = "/analytics/employee-reports";
  user = null;
  realApplied = false;
  scopeAccount = null;
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
  window.matchMedia = vi.fn().mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
});

describe("the denied-page panel", () => {
  it("replaces a denied page opened by URL, and the page fires no query", () => {
    applied = enforced(["/", "/messages-pro"]);
    renderShell();
    expect(screen.getByText("Your role does not allow this page")).toBeInTheDocument();
    expect(screen.queryByText("Employee reports page")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
    // The sidebar does not offer the denied page either.
    expect(screen.queryByRole("link", { name: "Employee reports" })).toBeNull();
    expect(screen.getByRole("link", { name: "Messages Pro" })).toBeInTheDocument();
  });

  it("a chatter granted no page at all lands on a pointer to the Help center instead of the bare denied line", () => {
    applied = enforced([]);
    renderShell();
    expect(screen.getByText("Your role does not give you any pages yet")).toBeInTheDocument();
    expect(screen.queryByText("Your role does not allow this page")).toBeNull();
    const help = screen.getAllByRole("link", { name: "Help center" });
    expect(help.some((a) => a.closest("main, [class*='max-w-shell']") && a.getAttribute("href") === "/help-center")).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders a granted page, which fires its query", () => {
    applied = enforced(["/analytics/employee-reports"]);
    renderShell();
    expect(screen.getByText("Employee reports page")).toBeInTheDocument();
    expect(screen.queryByText("Your role does not allow this page")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renders every page with pages: null", () => {
    applied = enforced(null);
    renderShell();
    expect(screen.getByText("Employee reports page")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("holds a chatter's page until the Applied settings read answers", () => {
    applied = { isLoading: true };
    renderShell();
    expect(screen.queryByText("Employee reports page")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps a chatter's page mounted while the read for a newly picked Creator loads", async () => {
    realApplied = true;
    let answerSecond: (r: Response) => void = () => {};
    const granted = () => jsonRes(enforced(["/analytics/employee-reports"]).data);
    fetchMock.mockImplementation((input) => {
      if (!String(input).includes("/admin/settings/applied")) return Promise.resolve(new Response("{}"));
      if (scopeAccount === null) return Promise.resolve(granted());
      return new Promise<Response>((resolve) => (answerSecond = resolve));
    });
    let mounts = 0;
    function MountCounter() {
      useEffect(() => {
        mounts += 1;
      }, []);
      return <p>Employee reports page</p>;
    }
    const { rerender } = renderWithProviders(
      <AppShell>
        <MountCounter />
      </AppShell>,
    );
    expect(await screen.findByText("Employee reports page")).toBeInTheDocument();
    expect(mounts).toBe(1);

    // The chatter picks another Creator: its read is still on the wire.
    scopeAccount = "acc-2";
    rerender(
      <AppShell>
        <MountCounter />
      </AppShell>,
    );
    expect(screen.getByText("Employee reports page")).toBeInTheDocument();
    await act(async () => answerSecond(granted()));
    expect(screen.getByText("Employee reports page")).toBeInTheDocument();
    expect(mounts).toBe(1);
  });

  it("never holds an owner's page while the read loads", () => {
    user = { username: "fixture-owner" };
    applied = { isLoading: true };
    renderShell();
    expect(screen.getByText("Employee reports page")).toBeInTheDocument();
  });
});
