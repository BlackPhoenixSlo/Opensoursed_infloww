/**
 * ChatSearch's Esc: it closes Find and spends the key (`preventDefault`), so
 * a page acting on an Esc nothing took (e.g. leaving a mode) stays put.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));

import { ChatSearch } from "@/components/chat/ChatSearch";
import { relay } from "@/lib/relay";
import type { FanId } from "@/lib/fanId";

describe("ChatSearch", () => {
  it("Esc closes it and is spent", () => {
    const onClose = vi.fn();
    render(
      <ChatSearch accountId="a" fanId={1 as FanId} messages={[]} ownerUserId={null}
        hasOlder={false} loadingOlder={false} onLoadOlder={vi.fn()} onPick={vi.fn()} onClose={onClose} />,
    );
    const notPrevented = fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(notPrevented).toBe(false);
  });
});

// loadOlder rejects on a failed / timed-out (15s) page: search must clear its
// "Loading…" states, never leak the rejection, stop auto-firing while
// olderFailed, and offer Retry.
describe("ChatSearch when an older page fails", () => {
  const timedOut = () => Promise.reject(new DOMException("older page timed out", "TimeoutError"));

  function setup(onLoadOlder: () => Promise<{ added: number; hasMore: boolean }>) {
    vi.mocked(relay.get).mockResolvedValue([501, 502] as never);
    const props = {
      accountId: "a", fanId: 1 as FanId, messages: [], ownerUserId: null,
      hasOlder: true, loadingOlder: false, onLoadOlder, onPick: vi.fn(), onClose: vi.fn(),
    };
    const r = render(<ChatSearch {...props} />);
    fireEvent.change(screen.getByPlaceholderText("Search this conversation…"), { target: { value: "hey" } });
    return { ...r, props };
  }

  it("auto-fill: the label clears, then olderFailed stops it and Retry loads once", async () => {
    const onLoadOlder = vi.fn(timedOut);
    const { rerender, props } = setup(onLoadOlder);
    await waitFor(() => expect(onLoadOlder).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText("Loading top previews…")).toBeNull());

    rerender(<ChatSearch {...props} olderFailed />);
    expect(onLoadOlder).toHaveBeenCalledTimes(1);   // no re-fire into the failure
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(onLoadOlder).toHaveBeenCalledTimes(2));
  });

  it("picking a not-loaded match: context label clears, no jump, says it failed", async () => {
    const onLoadOlder = vi.fn(timedOut);
    const { props } = setup(onLoadOlder);
    await waitFor(() => expect(onLoadOlder).toHaveBeenCalledTimes(1));   // auto-fill tried
    await waitFor(() => expect(screen.queryByText("Loading top previews…")).toBeNull());
    fireEvent.click(screen.getAllByText("Click to load context…")[0]);
    await waitFor(() => expect(screen.getByText("Couldn’t load older messages to reach that match.")).toBeTruthy());
    expect(screen.queryByText("Loading context…")).toBeNull();
    expect(props.onPick).not.toHaveBeenCalled();
  });
});
