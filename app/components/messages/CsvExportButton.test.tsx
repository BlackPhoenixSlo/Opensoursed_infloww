/**
 * CsvExportButton hides itself once the session's role denies the Export CSV Function permission
 * (any `<page>#export` in the Applied settings' `denied_actions`); the Relay refuses the download either way.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

let denied: string[] | undefined;
vi.mock("@/lib/appliedSettings", () => ({
  useAppliedSettings: () => ({ data: { permissions: { denied_actions: denied } } }),
}));

import CsvExportButton from "@/components/messages/CsvExportButton";

const renderButton = () => render(<CsvExportButton path="/admin/stats/sales-records" query="format=csv" />);

describe("CsvExportButton", () => {
  it("shows for a session with nothing denied, or with only another action denied", () => {
    denied = undefined;
    renderButton();
    expect(screen.getByRole("button", { name: /Export CSV/ })).toBeInTheDocument();
    denied = ["/messages-pro#unsend"];
    renderButton();
    expect(screen.getAllByRole("button", { name: /Export CSV/ })).toHaveLength(2);
  });

  it("is hidden once the role denies Export CSV under any page, as the Relay refuses it", () => {
    denied = ["/messages-pro#export"];
    renderButton();
    expect(screen.queryByRole("button", { name: /Export CSV/ })).toBeNull();
  });
});
