import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

const source = vi.hoisted(() => ({
  dismiss: vi.fn(),
  skip: vi.fn(),
  markSent: vi.fn(),
  calls: [] as Array<[string | null, unknown, string | null]>,
}));
vi.mock("@/lib/plugins.generated.register", () => ({
  PLUGINS: [{
    scriptSource: {
      owns: (id: string | null | undefined) => /^SRC\d+$/.test(id ?? ""),
      searchPrefix: "src",
      label: "source script",
      useSource: (accountId: string | null, fanId: unknown, at: string | null) => {
        source.calls.push([accountId, fanId, at]);
        return {
          scriptId: "SRC1",
          next: { scriptId: "SRC1", step: 1, label: "1", text: "source line one" },
          dismiss: source.dismiss,
          skip: source.skip,
          markSent: source.markSent,
        };
      },
      StepAction: ({ replyAt, onDraft }: { replyAt: string | null; onDraft: (t: string) => void }) => (
        <button type="button" data-testid="step-action" onClick={(e) => { e.stopPropagation(); onDraft(`drafted for ${replyAt}`); }}>Draft</button>
      ),
    },
  }],
}));
vi.mock("@/lib/relay", async (orig) =>
  (await import("./composerTestHarness")).mockRelayModule(await orig()));
vi.mock("./VaultPicker", async () =>
  (await import("./composerTestHarness")).vaultPickerStubModule);

import { resetComposerHarness, routeRelay } from "./composerTestHarness";
import type { SavedReply } from "@/lib/relay";
import { resetSendGapForTests } from "@/lib/sendGuards";
import { renderWithProviders } from "@/test-utils";

const row = (id: number, text: string, script_id: string | null, script_step: number | null): SavedReply => ({
  id, account_id: "acc", title: null, text, price: 0, locked_text: false, media: [], script_id, script_step,
});
const onSend = vi.fn(async (_a: { text: string }): Promise<undefined> => undefined);
beforeEach(() => {
  resetComposerHarness();
  window.sessionStorage.clear();
  window.localStorage.clear();
  source.calls.length = 0;
  routeRelay("/admin/saved-replies", () => ({ list: [
    row(1, "promo one", "Promo", 1), row(2, "source line one", "SRC1", 1), row(3, "other source line", "SRC2", 1),
  ] }));
});
afterEach(() => { cleanup(); onSend.mockClear(); source.dismiss.mockClear(); source.skip.mockClear(); source.markSent.mockClear(); });

async function mount() {
  const { Composer } = await import("./Composer");
  renderWithProviders(<Composer accountId="acc" fanId={7} fanSpokeLastAt="2026-10-20T10:05:00Z" onSend={onSend}
    placeholder="Message fan…" />);
}
const bubble = () => screen.queryByTitle("Tap to load this step into the composer");
const ta = () => screen.getByPlaceholderText("Message fan…") as HTMLTextAreaElement;

describe("the Composer's script source slot", () => {
  it("offers the source's step, read for the fan's last message, with its action beside it", async () => {
    await mount();
    await waitFor(() => expect(bubble()?.textContent).toContain("source line one"));
    expect(source.calls.at(-1)).toEqual(["acc", 7, "2026-10-20T10:05:00Z"]);
    fireEvent.click(screen.getByTestId("step-action"));
    await waitFor(() => expect(ta().value).toBe("drafted for 2026-10-20T10:05:00Z"));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("✕ goes to the source; a send of its step tells it", async () => {
    await mount();
    await waitFor(() => expect(bubble()).not.toBeNull());
    fireEvent.click(screen.getByTitle("End script — stop suggesting next steps"));
    expect(source.dismiss).toHaveBeenCalledTimes(1);
    fireEvent.click(bubble()!);
    await waitFor(() => expect(ta().value).toBe("source line one"));
    resetSendGapForTests();
    await act(async () => { fireEvent.keyDown(ta(), { key: "Enter" }); });
    await waitFor(() => expect(source.markSent).toHaveBeenCalledWith("SRC1", 1));
    expect(window.localStorage.getItem("chatterly:scriptCursor:acc:7")).toBeNull();
  });

  it("Skip goes to the source with the shown step and is disabled after loading", async () => {
    await mount();
    await waitFor(() => expect(bubble()).not.toBeNull());
    fireEvent.click(screen.getByTestId("script-skip"));
    expect(source.skip).toHaveBeenCalledWith("SRC1", 1);
    expect(ta().value).toBe("");
    fireEvent.click(bubble()!);
    await waitFor(() => expect(ta().value).toBe("source line one"));
    expect((screen.getByTestId("script-skip") as HTMLButtonElement).disabled).toBe(true);
    resetSendGapForTests();
    await act(async () => { fireEvent.keyDown(ta(), { key: "Enter" }); });
    await waitFor(() => expect(onSend).toHaveBeenCalled());
    expect(source.markSent).toHaveBeenCalledWith("SRC1", 1);
  });

  it("the Scripts picker lists the current source script first under its label and hides the others", async () => {
    await mount();
    fireEvent.click(screen.getByTitle("Insert saved template"));
    await screen.findByText("SRC1 · source script");
    expect(screen.queryByText("other source line")).toBeNull();
    expect(screen.getByText("promo one")).toBeTruthy();
  });
});
