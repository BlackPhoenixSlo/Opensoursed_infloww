import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import type { FeatureFlags } from "@/lib/appliedSettings";

vi.mock("@/lib/plugins.generated.register", () => ({ PLUGINS: [] }));
const nav = vi.hoisted(() => ({ search: "", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));
let flags: FeatureFlags | undefined;
vi.mock("@/components/shell/useFlags", () => ({ useFlags: () => flags }));
let granted: Set<string> | null = null;
vi.mock("@/components/shell/useGrantedPages", () => ({ useGrantedPages: () => granted }));
let chatterOnly = false;
vi.mock("@/components/shell/useIsChatterOnly", () => ({ useIsChatterOnly: () => chatterOnly }));

import Page from "./page";

beforeEach(() => {
  flags = { fansly_manager: true, leak_tracker: false };
  granted = null;
  chatterOnly = false;
  nav.search = "";
});
afterEach(() => {
  cleanup();
  nav.replace.mockClear();
});

describe("/fansly-manager", () => {
  it("lands on Homepage, keeping ?creator=", () => {
    nav.search = "creator=B";
    render(<Page />);
    expect(nav.replace).toHaveBeenCalledWith("/fansly-manager/home?creator=B");
  });

  it("with no creator picked lands on the bare entry", () => {
    render(<Page />);
    expect(nav.replace).toHaveBeenCalledWith("/fansly-manager/home");
  });

  it("a role without OnlyFans Home lands on the first entry it allows", () => {
    chatterOnly = true;
    granted = new Set(["/of-manager/queue"]);
    nav.search = "creator=B";
    render(<Page />);
    expect(nav.replace).toHaveBeenCalledWith("/fansly-manager/scheduled?creator=B");
  });

  it("waits for the flags before landing", () => {
    flags = undefined;
    render(<Page />);
    expect(nav.replace).not.toHaveBeenCalled();
    expect(screen.queryByText(/not available|does not allow/)).toBeNull();
  });

  it("with the flag off nothing is visible: not available, no landing", () => {
    flags = { fansly_manager: false, leak_tracker: false };
    render(<Page />);
    expect(screen.getByText("Fansly Manager is not available.")).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("with the flag on and no entry the role allows: the denied panel", () => {
    chatterOnly = true;
    granted = new Set(["/messages-pro"]);
    render(<Page />);
    expect(screen.getByText("Your role does not allow this page")).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });
});
