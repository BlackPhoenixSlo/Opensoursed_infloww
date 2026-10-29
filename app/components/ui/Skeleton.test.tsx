/**
 * The loading placeholders pages draw before their reads land: bars with no text (never "$0.00"), and the
 * automation pages' form while the account list is in flight instead of a blank body or the no-creator art.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { NoCreator } from "@/components/automations/automationPage";
import { SkeletonRows, TableSkeleton } from "@/components/ui/Skeleton";

afterEach(cleanup);

describe("TableSkeleton", () => {
  it("draws a header and the asked rows as bars, no text", () => {
    const { container } = render(<TableSkeleton rows={3} />);
    const root = container.firstElementChild!;
    expect(root.children).toHaveLength(4);
    expect(root.textContent).toBe("");
    expect(container.querySelectorAll("[data-loading]").length).toBe(4 + 3 * 5);
  });
});

describe("SkeletonRows", () => {
  it("fills a page's own table body: the asked rows and columns, one bar a cell, hidden from readers, no text", () => {
    const { container } = render(<table><tbody><SkeletonRows rows={4} cols={3} cellClassName="px-2" /></tbody></table>);
    const rows = container.querySelectorAll("tbody > tr");
    expect(rows).toHaveLength(4);
    for (const r of rows) {
      expect(r.getAttribute("aria-hidden")).toBe("true");
      expect(r.querySelectorAll("td.px-2 > [data-loading]")).toHaveLength(3);
    }
    expect(container.textContent).toBe("");
  });
});

describe("NoCreator", () => {
  it("while the account list loads: the form's placeholder bars, a status, no no-creator art", () => {
    const { container } = render(<NoCreator loading />);
    expect(screen.getByRole("status", { name: "Loading" })).toBeTruthy();
    expect(screen.queryByText("No creator with a live session")).toBeNull();
    expect(container.querySelectorAll("[data-loading]").length).toBeGreaterThan(4);
    expect(container.textContent).toBe("");
  });

  it("once it has answered with no live Creator: the no-creator state", () => {
    render(<NoCreator />);
    expect(screen.getByText("No creator with a live session")).toBeTruthy();
  });
});
