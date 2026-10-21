/** OF Manager's chat: Messages Pro's Fan insights and Scripts beside it (W8 8.5). */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import type { PickedTemplate } from "@/components/chat/TemplatePicker";

let chat: string | null = "9001";
let desktop = true;
vi.mock("@/hooks/useIsDesktop", () => ({ useIsDesktop: () => desktop }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(chat ? `chat=${chat}` : "") }));
const get = vi.fn(async (_path: string, _opts?: unknown) => ({ withUser: { id: 9001 } }));
vi.mock("@/lib/relay", () => ({ relay: { get: (path: string, opts?: unknown) => get(path, opts) } }));
vi.mock("@/lib/events", () => ({ eventBus: { setScope: vi.fn(), on: () => () => {}, onStateChange: () => () => {} } }));
const drawer = vi.fn();
vi.mock("@/components/chat/FanDrawer", () => ({
  FanDrawer: (p: { fanId: unknown; onClose(): void }) => {
    drawer(p);
    return <button type="button" onClick={p.onClose}>close insights</button>;
  },
}));
const SCRIPT: PickedTemplate = { source: "local", text: "Script hi", displayText: "Script hi", mediaCount: 1, price: 0, lockedText: false, isWelcome: false, media: [{ id: 61, type: "photo" }], previews: [], taggedUsers: [] };
vi.mock("@/components/chat/TemplatePicker", () => ({
  TemplatePicker: (p: { onPick(t: PickedTemplate): void }) => <button type="button" onClick={() => p.onPick(SCRIPT)}>Scripts</button>,
}));

import { renderWithProviders } from "@/test-utils";
import { ScopeProvider } from "@/contexts/ScopeContext";
import { chatDraftKey } from "@/lib/ofMirrorChat";
import { CHAT_SRC, OfChatSidePanel } from "./OfChatSidePanel";

const ui = (src = CHAT_SRC) =>
  renderWithProviders(
    <ScopeProvider>
      <OfChatSidePanel frameRef={{ current: null }} src={src} />
    </ScopeProvider>,
  );

beforeEach(() => {
  localStorage.setItem("chatterly:scope", "model:acct-1");
  sessionStorage.clear();
  chat = "9001";
  desktop = true;
});
afterEach(() => {
  cleanup();
  localStorage.clear();
  get.mockClear();
  drawer.mockClear();
});

describe("OfChatSidePanel", () => {
  it("an open chat shows Fan insights for its fan (a number, as the inbox keys it) once the chat is read", async () => {
    ui();
    expect(await screen.findByTestId("of-chat-panel")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/of/v2/chats/9001", { accountId: "acct-1" });
    expect(drawer.mock.calls[0][0]).toMatchObject({ fanId: 9001, accountId: "acct-1", pinned: true });
  });

  it("a picked script goes on the chat's draft", async () => {
    ui();
    fireEvent.click(await screen.findByText("Scripts"));
    expect(JSON.parse(sessionStorage.getItem(chatDraftKey("acct-1", "9001"))!)).toMatchObject({ text: "Script hi", media_files: [61] });
  });

  it("its × folds it to a Fan insights button that opens it again", async () => {
    ui();
    fireEvent.click(await screen.findByText("close insights"));
    expect(screen.queryByTestId("of-chat-panel")).toBeNull();
    fireEvent.click(screen.getByTestId("of-chat-panel-open"));
    expect(screen.getByTestId("of-chat-panel")).toBeInTheDocument();
  });

  it("nothing with no chat open, on another page, or with no model", () => {
    chat = null;
    ui();
    cleanup();
    chat = "9001";
    ui("/of-mirror/pages/messages/chat/state-price.html");
    cleanup();
    localStorage.setItem("chatterly:scope", "all");
    ui();
    expect(screen.queryByTestId("of-chat-panel")).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });

  it("nothing below lg: no Fan insights mounted, no chat read", () => {
    desktop = false;
    ui();
    expect(screen.queryByTestId("of-chat-panel")).toBeNull();
    expect(screen.queryByTestId("of-chat-panel-open")).toBeNull();
    expect(get).not.toHaveBeenCalled();
    expect(drawer).not.toHaveBeenCalled();
  });
});
