/**
 * ChatSearch's Esc: it closes Find and spends the key (`preventDefault`), so
 * a page acting on an Esc nothing took (e.g. leaving a mode) stays put.
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";

vi.mock("@/lib/relay", () => ({ relay: { get: vi.fn() } }));

import { ChatSearch } from "@/components/chat/ChatSearch";
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
