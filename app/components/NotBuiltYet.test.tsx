/**
 * NotBuiltYetRoute — the Fansly Manager pages show Infloww's pre-Start
 * welcome; the Start button is the one place that says "not built".
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
// PlatformSwitcher's module reads the platform store; the logo alone is drawn here.
vi.mock("@/components/shell/PlatformSwitcher", () => ({
  PlatformLogo: ({ platform }: { platform: string }) => <svg data-testid={`platform-logo-${platform}`} />,
}));

import { NotBuiltYetRoute } from "./NotBuiltYet";

afterEach(cleanup);

describe("NotBuiltYetRoute", () => {
  it("renders the Fansly welcome with a disabled Start", () => {
    render(<NotBuiltYetRoute href="/fansly-manager/home" />);
    expect(screen.getByText("Grow your revenue on Fansly with Inflowwww")).toBeTruthy();
    const start = screen.getByRole("button", { name: "Start" }) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    const h1 = screen.getByRole("heading", { level: 1, name: "Homepage" });
    expect(h1.className).toContain("sr-only");
    // The Route walk finds placeholders by this substring.
    expect(screen.getByText(/Homepage is not built yet\./)).toBeTruthy();
    expect(screen.getByTestId("platform-logo-fansly")).toBeTruthy();
  });

  it("is a 404 for an href the nav tree does not list as unbuilt", () => {
    expect(() => render(<NotBuiltYetRoute href="/fansly-manager/nope" />)).toThrow("NEXT_NOT_FOUND");
    expect(() => render(<NotBuiltYetRoute href="/dashboard" />)).toThrow("NEXT_NOT_FOUND");
  });
});
