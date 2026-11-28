import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, screen } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";

vi.mock("@/lib/relay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/relay")>()),
  relay: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import AddCreatorModal, { type SectionKey } from "@/components/setup/AddCreatorModal";
import { platformRow, type Platform } from "@/lib/platform";
import { relay } from "@/lib/relay";

beforeEach(() => {
  (relay.get as unknown as Mock).mockReset().mockResolvedValue({});
});
afterEach(cleanup);

describe("AddCreatorModal submit target", () => {
  it.each<[Platform, SectionKey, string]>([
    ["onlyfans", "paste", "extension-login-form"],
    ["fansly", "fansly", "fansly-session-form"],
  ])("%s extension sign-in: the footer submit targets the row's extensionFormId", (key, at, formId) => {
    renderWithProviders(<AddCreatorModal extInstalled={null} at={at} onClose={() => {}} />);
    const footer = screen.getByRole("dialog").lastElementChild as HTMLElement;
    const submits = [...footer.querySelectorAll('button[type="submit"]')];
    expect(submits.map((b) => b.getAttribute("form"))).toEqual([formId]);
    expect(platformRow(key)?.extensionFormId).toBe(formId);
    expect(document.getElementById(formId)?.tagName).toBe("FORM");
  });
});
