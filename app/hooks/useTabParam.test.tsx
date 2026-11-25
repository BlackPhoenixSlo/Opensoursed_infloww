import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { useTabParam } from "./useTabParam";

afterEach(cleanup);

type Tab = "smart" | "promotion";
const isTab = (v: string): v is Tab => v === "smart" || v === "promotion";

function setSearch(search: string) {
  window.history.replaceState({}, "", `/growth${search}`);
}

function Probe({ onFound }: { onFound: (t: Tab) => void }) {
  useTabParam("tab", isTab, onFound);
  return null;
}

describe("useTabParam", () => {
  it("seeds the tab named in the URL", () => {
    setSearch("?tab=promotion");
    const found = vi.fn();
    render(<Probe onFound={found} />);
    expect(found).toHaveBeenCalledWith("promotion");
  });

  it("ignores a tab the page does not own", () => {
    setSearch("?tab=employees");
    const found = vi.fn();
    render(<Probe onFound={found} />);
    expect(found).not.toHaveBeenCalled();
  });

  it("does nothing without the param", () => {
    setSearch("");
    const found = vi.fn();
    render(<Probe onFound={found} />);
    expect(found).not.toHaveBeenCalled();
  });

  it("fires once, so a re-render cannot yank the reader off their tab", () => {
    setSearch("?tab=promotion");
    const found = vi.fn();
    const { rerender } = render(<Probe onFound={found} />);
    rerender(<Probe onFound={found} />);
    rerender(<Probe onFound={found} />);
    expect(found).toHaveBeenCalledTimes(1);
  });
});
