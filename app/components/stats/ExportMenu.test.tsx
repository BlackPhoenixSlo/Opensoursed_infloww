/**
 * ExportMenu, the reports' Export pop-up: it offers the choices the page passes (fields, Gross / Net, the
 * displays), hands `build` the choice, and downloads the sections as CSV, or as Excel through the Relay's
 * `POST /admin/stats/xlsx`. Hidden once the role denies Export CSV.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

let denied: string[] | undefined;
vi.mock("@/lib/appliedSettings", () => ({
  useAppliedSettings: () => ({ data: { permissions: { denied_actions: denied } } }),
}));
const relayFile = vi.fn();
vi.mock("@/lib/relay", () => ({ relayFile: (...args: unknown[]) => relayFile(...args) }));

import ExportMenu, { type ExportChoice } from "@/components/stats/ExportMenu";

const SECTIONS = [{ title: "Total", rows: [["Creator", "Total earnings"], ["=Ann", 12.5]] }];

/** Captures the saved blob: jsdom has no object URLs, so lend them for the test. */
function captureDownload() {
  const saved: { blob: Blob | null; name: string | null } = { blob: null, name: null };
  const orig = { create: URL.createObjectURL, revoke: URL.revokeObjectURL };
  URL.createObjectURL = vi.fn((b: Blob) => { saved.blob = b; return "blob:export"; });
  URL.revokeObjectURL = vi.fn();
  onTestFinished(() => { URL.createObjectURL = orig.create; URL.revokeObjectURL = orig.revoke; });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    saved.name = this.download;
  });
  return saved;
}

beforeEach(() => {
  denied = undefined;
  relayFile.mockReset();
});
afterEach(() => vi.restoreAllMocks());

describe("ExportMenu", () => {
  it("offers the page's choices and hands build what was picked", async () => {
    captureDownload();
    const build = vi.fn((_: ExportChoice) => SECTIONS);
    render(<ExportMenu fileName="creator-reports" sheet="Creator reports" displays={["total", "day"]} fields net
      build={build} />);
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(screen.getByLabelText("Display total")).toBeChecked();
    expect(screen.getByLabelText("Display by day")).not.toBeChecked();
    expect(screen.getByLabelText("Net")).toBeChecked();
    expect(screen.getByLabelText("Selected fields")).toBeChecked();
    expect(screen.queryByLabelText("Display by creator")).toBeNull();

    fireEvent.click(screen.getByLabelText("Display by day"));
    fireEvent.click(screen.getByLabelText("All data fields"));
    fireEvent.click(screen.getByLabelText("Gross"));
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(build).toHaveBeenCalledTimes(1));
    expect(build.mock.calls[0][0]).toEqual({ displays: ["total", "day"], allFields: true, net: false, format: "csv" });
  });

  it("hides fields and earnings where the page has none, and needs a display ticked", () => {
    render(<ExportMenu fileName="e" sheet="E" displays={["total", "day", "creator"]} build={() => SECTIONS} />);
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    expect(screen.queryByLabelText("All data fields")).toBeNull();
    expect(screen.queryByLabelText("Net")).toBeNull();
    fireEvent.click(screen.getByLabelText("Display total"));
    expect(screen.getByRole("button", { name: "Download" })).toBeDisabled();
  });

  it("downloads CSV with formula-like cells escaped, then closes", async () => {
    const saved = captureDownload();
    render(<ExportMenu fileName="creator-reports_2026-10-01_2026-10-31" sheet="Creator reports" displays={["total"]}
      build={() => SECTIONS} />);
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(saved.name).toBe("creator-reports_2026-10-01_2026-10-31.csv");
    expect(await saved.blob!.text()).toBe("Creator,Total earnings\n'=Ann,12.5");
    expect(relayFile).not.toHaveBeenCalled();
  });

  it("downloads Excel through the Relay with the rows as built", async () => {
    const saved = captureDownload();
    const xlsx = new Blob(["xlsx"]);
    relayFile.mockResolvedValue({ blob: xlsx, name: "report.xlsx" });
    render(<ExportMenu fileName="employee-reports" sheet="Employee reports" displays={["total"]}
      build={() => SECTIONS} />);
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    fireEvent.click(screen.getByLabelText("Excel (.xlsx)"));
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => expect(saved.name).toBe("employee-reports.xlsx"));
    expect(relayFile).toHaveBeenCalledWith("/admin/stats/xlsx", undefined,
      { sheet: "Employee reports", rows: SECTIONS[0].rows });
    expect(saved.blob).toBe(xlsx);
  });

  it("shows a failed build or download and stays open", async () => {
    render(<ExportMenu fileName="e" sheet="E" displays={["day"]}
      build={() => Promise.reject(new Error("by-day read failed"))} />);
    fireEvent.click(screen.getByRole("button", { name: "Export" }));
    fireEvent.click(screen.getByRole("button", { name: "Download" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("by-day read failed");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("is hidden once the role denies Export CSV under any page", () => {
    denied = ["/analytics/sales-records#export"];
    render(<ExportMenu fileName="e" sheet="E" displays={["total"]} build={() => SECTIONS} />);
    expect(screen.queryByRole("button", { name: "Export" })).toBeNull();
  });
});
