import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test-utils";

import VaultTagChips from "./VaultTagChips";

const h = vi.hoisted(() => ({ facets: { data: undefined as unknown, isPlaceholderData: false } }));
vi.mock("@/hooks/useVaultCache", () => ({
  useTagFacets: () => h.facets,
  invalidateVaultGrid: vi.fn(),
  publishFolderToOf: vi.fn(),
  saveTagFolder: vi.fn(),
}));

function renderChips(tags: string[]) {
  renderWithProviders(
    <VaultTagChips accountId="a" enabled type="all" query="" ofFolderId={null} tags={tags}
      onToggle={() => {}} onClear={() => {}} />,
  );
}

describe("Save as folder", () => {
  it("is off while a chip tap's counts load (the shown count is the previous view's)", () => {
    h.facets = { data: { tags: [{ tag: "feet", count: 12 }], total: 12, selected: [] }, isPlaceholderData: true };
    renderChips(["feet"]);
    fireEvent.click(screen.getByRole("button", { name: "Save as folder" }));
    expect(screen.getByRole("button", { name: "Counting…" })).toBeDisabled();
  });

  it("is on once the counts are this view's", () => {
    h.facets = { data: { tags: [{ tag: "feet", count: 3 }], total: 3, selected: ["feet"] }, isPlaceholderData: false };
    renderChips(["feet"]);
    fireEvent.click(screen.getByRole("button", { name: "Save as folder" }));
    expect(screen.getByRole("button", { name: "Save 3 items" })).toBeEnabled();
  });
});
