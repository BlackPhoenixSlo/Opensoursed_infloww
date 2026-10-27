/**
 * useChatBackEntry: below lg an open Thread has its own history entry, so the
 * platform's back closes the Thread before leaving Messages Pro, and the
 * Thread's own back (button, swipe) goes through that same entry.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CHAT_ENTRY, keepChatEntry, useChatBackEntry } from "./useChatBackEntry";

let wide = false;
beforeEach(() => {
  wide = false;
  window.matchMedia = vi.fn(() => ({
    matches: wide, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
  window.history.replaceState(null, "", "/messages-pro");
});

function Pane({ start = false }: { start?: boolean }) {
  const [open, setOpen] = useState(start);
  const back = useChatBackEntry(true, open, () => setOpen(false));
  return (
    <>
      <p data-testid="pane">{open ? "thread" : "list"}</p>
      <button onClick={() => setOpen(true)}>open</button>
      <button onClick={() => setOpen(false)}>close</button>
      <button onClick={back}>back</button>
    </>
  );
}
const marked = () => (window.history.state as Record<string, unknown> | null)?.[CHAT_ENTRY] === true;
const press = (name: string) => fireEvent.click(screen.getByRole("button", { name }));
const pane = () => screen.getByTestId("pane");

describe("useChatBackEntry", () => {
  it("pushes a marked same-URL entry when a Thread opens; back closes it and leaves the entry", async () => {
    const len = window.history.length;
    render(<Pane />);
    press("open");
    expect(window.history.length).toBe(len + 1);
    expect(marked()).toBe(true);
    expect(window.location.pathname).toBe("/messages-pro");

    act(() => window.history.back());
    await waitFor(() => expect(pane()).toHaveTextContent("list"));
    expect(marked()).toBe(false);
  });

  it("an in-app close pops the marked entry", async () => {
    render(<Pane />);
    press("open");
    expect(marked()).toBe(true);
    press("close");
    await waitFor(() => expect(marked()).toBe(false));
  });

  it("the Thread's back (button, swipe) goes back in history once; popstate closes the Thread", async () => {
    const go = vi.spyOn(window.history, "back");
    render(<Pane />);
    press("open");
    press("back");
    await waitFor(() => expect(pane()).toHaveTextContent("list"));
    expect(go).toHaveBeenCalledTimes(1);
    expect(marked()).toBe(false);
    go.mockRestore();
  });

  it("a Forward back onto the Thread's entry stays there (unmarked) and a further Forward still works", async () => {
    render(<Pane />);
    press("open");
    window.history.pushState({ later: true }, "", "/later");        // a page opened from the chat
    act(() => window.history.back());                               // back onto the open chat's entry
    await waitFor(() => expect(window.location.pathname).toBe("/messages-pro"));
    act(() => window.history.back());                               // back to the Fan List
    await waitFor(() => expect(pane()).toHaveTextContent("list"));

    const go = vi.spyOn(window.history, "back");
    act(() => window.history.forward());                            // Forward onto the chat's entry
    await waitFor(() => expect(marked()).toBe(false));
    expect(go).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe("/messages-pro");
    expect(pane()).toHaveTextContent("list");
    act(() => window.history.forward());
    await waitFor(() => expect(window.location.pathname).toBe("/later"));
    go.mockRestore();
  });

  it("at desktop width the Thread's back just closes it", () => {
    wide = true;
    const go = vi.spyOn(window.history, "back");
    render(<Pane start />);
    press("back");
    expect(pane()).toHaveTextContent("list");
    expect(go).not.toHaveBeenCalled();
    go.mockRestore();
  });

  it("a marked entry with no Thread open (a reload) is popped", async () => {
    window.history.pushState({ [CHAT_ENTRY]: true }, "");
    render(<Pane />);
    await waitFor(() => expect(marked()).toBe(false));
  });

  it("under Strict Mode (effects run twice) a reload's marked entry is popped once, not past Messages Pro", async () => {
    window.history.pushState({ [CHAT_ENTRY]: true }, "");
    const go = vi.spyOn(window.history, "back");
    render(<StrictMode><Pane /></StrictMode>);
    await waitFor(() => expect(marked()).toBe(false));
    expect(go).toHaveBeenCalledTimes(1);
    go.mockRestore();
  });

  it("under Strict Mode an opened Thread pushes one entry", () => {
    const push = vi.spyOn(window.history, "pushState");
    render(<StrictMode><Pane /></StrictMode>);
    press("open");
    expect(push).toHaveBeenCalledTimes(1);
    expect(marked()).toBe(true);
    push.mockRestore();
  });

  it("never pushes at desktop width", () => {
    wide = true;
    const len = window.history.length;
    render(<Pane start />);
    expect(window.history.length).toBe(len);
    expect(marked()).toBe(false);
  });

  it("keepChatEntry carries the mark only on a marked entry", () => {
    expect(keepChatEntry()).toBeNull();
    window.history.pushState({ [CHAT_ENTRY]: true }, "");
    expect(keepChatEntry()).toEqual({ [CHAT_ENTRY]: true });
  });
});
