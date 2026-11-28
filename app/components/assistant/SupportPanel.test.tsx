import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

type HubMsg = { id: number; from: string; text: string; at: string; photos?: Array<{ id: number; w: number; h: number }> };

const { relayPost, relayGet, relayUpload, signedIn, hub } = vi.hoisted(() => ({
  relayPost: vi.fn(),
  relayGet: vi.fn(),
  relayUpload: vi.fn(),
  signedIn: { user: { username: "owner", user_id: "u1" } as { username: string; user_id?: string } | null },
  hub: { configured: true, unread: 0, messages: [] as HubMsg[] },
}));

vi.mock("@/lib/relay", () => ({
  RelayError: class extends Error {},
  relay: {
    post: (...a: unknown[]) => relayPost(...a), get: (...a: unknown[]) => relayGet(...a), put: vi.fn(),
    uploadForm: (...a: unknown[]) => relayUpload(...a),
  },
  relayFile: vi.fn(),
}));
vi.mock("./supportPhoto", () => ({
  toJpeg: (f: Blob) => Promise.resolve(new Blob([f], { type: "image/jpeg" })),
  imageFiles: (list: FileList | File[] | null | undefined) => Array.from(list ?? []).filter((f) => f.type.startsWith("image/")),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/", useRouter: () => ({ push: () => {} }) }));
vi.mock("@/contexts/ScopeContext", () => ({ useScope: () => ({ accountId: null }) }));
vi.mock("@/contexts/EmployeeContext", () => ({ useEmployee: () => ({ current: { id: 7 } }) }));
vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => ({ data: { accounts: [] }, isSuccess: true, dataUpdatedAt: 1 }),
}));
vi.mock("@/contexts/UserContext", () => ({ useOptionalUser: () => (signedIn.user ? { user: signedIn.user } : null) }));

import { renderWithProviders } from "@/test-utils";
import { AssistantProvider, AssistantWidget } from "./AssistantWidget";
import { SUPPORT_EMPTY } from "./SupportPanel";
import { SUPPORT_FALLBACK_ERROR, SUPPORT_POLL_MS, SUPPORT_THREAD_POLL_MS } from "./supportReducer";
import { PageCreatorProvider } from "@/contexts/PageCreatorContext";

const tree = () => <PageCreatorProvider><AssistantProvider><AssistantWidget /></AssistantProvider></PageCreatorProvider>;
const unreadCalls = () => relayGet.mock.calls.filter(([p]) => p === "/admin/support/unread").length;

beforeEach(() => {
  relayPost.mockReset();
  relayGet.mockReset();
  relayUpload.mockReset();
  URL.createObjectURL = vi.fn(() => "blob:preview");
  URL.revokeObjectURL = vi.fn();
  relayUpload.mockImplementation((path: string, form: FormData) => {
    if (path !== "/admin/support/messages/upload") return Promise.resolve({});
    const photos = form.getAll("photos").map((_p, i) => ({ id: 100 + i, w: 10, h: 10 }));
    hub.messages = [...hub.messages, { id: hub.messages.length + 1, from: "me", text: String(form.get("text") ?? ""), at: "", photos }];
    return Promise.resolve({ configured: true, messages: hub.messages });
  });
  hub.configured = true;
  hub.unread = 0;
  hub.messages = [];
  signedIn.user = { username: "owner", user_id: "u1" };
  relayGet.mockImplementation((path: string) => {
    if (path === "/admin/support/unread") {
      return Promise.resolve(hub.configured ? { configured: true, unread: hub.unread } : { configured: false });
    }
    if (path === "/admin/support/thread") return Promise.resolve({ configured: true, messages: hub.messages });
    return Promise.resolve({ count: 0, since_hours: 24, list: [], turns: [] });
  });
  relayPost.mockImplementation((path: string, body: { text?: string }) => {
    if (path === "/admin/support/read") { hub.unread = 0; return Promise.resolve({ configured: true, ok: true }); }
    if (path === "/admin/assistant/ask") return Promise.resolve({ answer: "Not supported yet.", error: null });
    if (path === "/admin/support/messages") {
      hub.messages = [...hub.messages, { id: hub.messages.length + 1, from: "me", text: body.text ?? "", at: "" }];
      return Promise.resolve({ configured: true, messages: hub.messages });
    }
    return Promise.resolve({});
  });
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

async function openHelp() {
  renderWithProviders(tree());
  await userEvent.click(await screen.findByRole("button", { name: "Help assistant" }));
}

describe("Support tab", () => {
  it("clears the open Support thread and draft when the principal changes", async () => {
    hub.messages = [{ id: 1, from: "me", text: "Previous thread", at: "" }];
    const view = renderWithProviders(tree());
    await userEvent.click(await screen.findByRole("button", { name: "Help assistant" }));
    await userEvent.click(await screen.findByRole("button", { name: "Support" }));
    await screen.findByText("Previous thread");
    await userEvent.type(screen.getByRole("textbox", { name: "Message Support" }), "Previous draft");
    await userEvent.upload(screen.getByLabelText("Choose photos"), new File(["img"], "a.png", { type: "image/png" }));
    await screen.findByAltText("Photo to send");

    signedIn.user = { username: "master", user_id: "u2" };
    hub.messages = [];
    view.rerender(tree());
    await userEvent.click(await screen.findByRole("button", { name: "Support" }));
    await screen.findByText(SUPPORT_EMPTY);
    expect(screen.getByRole("textbox", { name: "Message Support" })).toHaveValue("");
    expect(screen.queryByText("Previous thread")).toBeNull();
    expect(screen.queryByAltText("Photo to send")).toBeNull();
  });

  it("keeps the draft and photo when the relay reports Support unavailable", async () => {
    relayUpload.mockResolvedValueOnce({ configured: false });
    await openHelp();
    await userEvent.click(await screen.findByRole("button", { name: "Support" }));
    await screen.findByText(SUPPORT_EMPTY);
    await userEvent.upload(screen.getByLabelText("Choose photos"), new File(["img"], "a.png", { type: "image/png" }));
    await screen.findByAltText("Photo to send");
    const input = screen.getByRole("textbox", { name: "Message Support" });
    await userEvent.type(input, "try again{Enter}");
    await screen.findByText(SUPPORT_FALLBACK_ERROR);
    expect(input).toHaveValue("try again");
    expect(screen.getByAltText("Photo to send")).toBeInTheDocument();
    expect(hub.messages).toEqual([]);
  });

  it("is hidden when the hub is not configured", async () => {
    hub.configured = false;
    await openHelp();
    await waitFor(() => expect(unreadCalls()).toBe(1));
    expect(screen.queryByRole("button", { name: /^Support/ })).toBeNull();
  });

  it("asks nothing when signed out of a principal", async () => {
    signedIn.user = { username: "anon" };
    await openHelp();
    expect(unreadCalls()).toBe(0);
  });

  it("opens with the empty note, sends, and marks read", async () => {
    await openHelp();
    await userEvent.click(await screen.findByRole("button", { name: "Support" }));
    expect(await screen.findByText(SUPPORT_EMPTY)).toBeInTheDocument();
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/support/read", { up_to: 0 }));
    const box = screen.getByRole("textbox", { name: "Message Support" });
    await userEvent.type(box, "Need bulk tags{Shift>}{Enter}{/Shift}please{Enter}");
    await screen.findByText(/Need bulk tags/);
    expect(relayPost).toHaveBeenCalledWith("/admin/support/messages", { text: "Need bulk tags\nplease" });
    expect(box).toHaveValue("");
    await userEvent.click(screen.getByRole("button", { name: "Back to help" }));
    expect(screen.getByPlaceholderText("Ask a question…")).toBeInTheDocument();
  });

  it("renders markup in a message as text", async () => {
    hub.messages = [{ id: 1, from: "support", text: "<img src=x onerror=alert(1)> thanks", at: "" }];
    await openHelp();
    await userEvent.click(await screen.findByRole("button", { name: "Support" }));
    expect(await screen.findByText("<img src=x onerror=alert(1)> thanks")).toBeInTheDocument();
    expect(document.querySelector("[data-support] img")).toBeNull();
  });

  it("an unread reply puts a dot on the closed launcher and clears once opened", async () => {
    hub.unread = 1;
    hub.messages = [{ id: 1, from: "me", text: "hi", at: "" }, { id: 2, from: "support", text: "On it", at: "" }];
    renderWithProviders(tree());
    expect(await screen.findByLabelText("New reply")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Help assistant" }));
    await userEvent.click(await screen.findByRole("button", { name: "Support (new reply)" }));
    expect(await screen.findByText("On it")).toBeInTheDocument();
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/support/read", { up_to: 2 }));
    await userEvent.click(screen.getByRole("button", { name: "Back to help" }));
    expect(screen.getByRole("button", { name: "Support" })).toBeInTheDocument();
  });

  it("polls every 60 s only while visible and configured", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const tick = (ms: number) => act(async () => { vi.advanceTimersByTime(ms); await new Promise((r) => setTimeout(r, 0)); });
    renderWithProviders(tree());
    await tick(0);
    expect(unreadCalls()).toBe(1);
    await tick(SUPPORT_POLL_MS - 1);
    expect(unreadCalls()).toBe(1);
    await tick(1);
    expect(unreadCalls()).toBe(2);
    const vis = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await tick(SUPPORT_POLL_MS * 3);
    expect(unreadCalls()).toBe(2);
    vis.mockRestore();
    hub.configured = false;
    await tick(SUPPORT_POLL_MS);
    expect(unreadCalls()).toBe(3);
    await tick(SUPPORT_POLL_MS * 3);
    expect(unreadCalls()).toBe(3);
  });

  it("sends up to four photos with text and shows them as links", async () => {
    await openHelp();
    await userEvent.click(await screen.findByRole("button", { name: "Support" }));
    await screen.findByText(SUPPORT_EMPTY);
    const input = screen.getByLabelText("Choose photos") as HTMLInputElement;
    const file = (n: string) => new File(["img"], n, { type: "image/png" });
    await userEvent.upload(input, [file("a.png"), file("b.png")]);
    expect(await screen.findAllByAltText("Photo to send")).toHaveLength(2);
    await userEvent.click(screen.getAllByRole("button", { name: "Remove photo" })[0]);
    expect(screen.getAllByAltText("Photo to send")).toHaveLength(1);
    await userEvent.upload(input, [file("c.png"), file("d.png"), file("e.png"), file("f.png")]);
    expect(await screen.findByText("Up to 4 photos per message.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByAltText("Photo to send")).toHaveLength(4));
    expect(screen.getByRole("button", { name: "Add photos" })).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Message Support" }), "see shots{Enter}");
    await waitFor(() => expect(relayUpload).toHaveBeenCalledTimes(1));
    const form = relayUpload.mock.calls[0][1] as FormData;
    expect(form.get("text")).toBe("see shots");
    expect(form.getAll("photos")).toHaveLength(4);
    expect(relayPost).not.toHaveBeenCalledWith("/admin/support/messages", expect.anything());
    const sent = await screen.findAllByAltText("Photo");
    expect(sent.map((i) => i.getAttribute("src"))).toEqual([100, 101, 102, 103].map((id) => `/admin/support/photos/${id}`));
    expect(sent[0].closest("a")?.getAttribute("target")).toBe("_blank");
    expect(screen.queryByAltText("Photo to send")).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalled();
  });

  it("an open thread polls every 4 s, merging new replies without touching the draft", async () => {
    hub.messages = [{ id: 1, from: "me", text: "hi", at: "" }];
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    await openHelp();
    await userEvent.click(await screen.findByRole("button", { name: "Support" }));
    await screen.findByText("hi");
    const box = screen.getByRole("textbox", { name: "Message Support" });
    await userEvent.type(box, "half typed");
    const threadCalls = () => relayGet.mock.calls.filter(([p]) => p === "/admin/support/thread").length;
    const before = threadCalls();
    hub.messages = [...hub.messages, { id: 2, from: "support", text: "Fixed now", at: "" }];
    relayPost.mockClear();
    await act(async () => { vi.advanceTimersByTime(SUPPORT_THREAD_POLL_MS); await new Promise((r) => setTimeout(r, 0)); });
    expect(await screen.findByText("Fixed now")).toBeInTheDocument();
    expect(threadCalls()).toBe(before + 1);
    expect(box).toHaveValue("half typed");
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/support/read", { up_to: 2 }));
    const vis = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await act(async () => { vi.advanceTimersByTime(SUPPORT_THREAD_POLL_MS * 3); await new Promise((r) => setTimeout(r, 0)); });
    expect(threadCalls()).toBe(before + 1);
    vis.mockRestore();
  });

  it("skips polling while a thread request is pending", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    relayGet.mockImplementation((path: string) => {
      if (path === "/admin/support/unread") return Promise.resolve({ configured: true, unread: 0 });
      if (path === "/admin/support/thread") return new Promise(() => {});
      return Promise.resolve({});
    });
    await openHelp();
    await userEvent.click(await screen.findByRole("button", { name: "Support" }));
    const reads = () => relayGet.mock.calls.filter(([path]) => path === "/admin/support/thread").length;
    await waitFor(() => expect(reads()).toBe(1));
    await act(async () => { vi.advanceTimersByTime(SUPPORT_THREAD_POLL_MS * 2); });
    expect(reads()).toBe(1);
  });

  it("a failed read is retried on the next poll", async () => {
    hub.messages = [{ id: 1, from: "me", text: "hi", at: "" }];
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    await openHelp();
    await userEvent.click(await screen.findByRole("button", { name: "Support" }));
    await screen.findByText("hi");
    hub.messages = [...hub.messages, { id: 2, from: "support", text: "Reply", at: "" }];
    const reads = () => relayPost.mock.calls.filter(([p]) => p === "/admin/support/read").length;
    const base = relayPost.getMockImplementation()!;
    relayPost.mockImplementation((path: string, body: { text?: string }) =>
      path === "/admin/support/read" ? Promise.reject(new Error("down")) : base(path, body));
    const before = reads();
    const tick = () => act(async () => { vi.advanceTimersByTime(SUPPORT_THREAD_POLL_MS); await new Promise((r) => setTimeout(r, 0)); });
    await tick();
    await waitFor(() => expect(reads()).toBe(before + 1));
    relayPost.mockImplementation(base);
    await tick();
    await waitFor(() => expect(reads()).toBe(before + 2));
    await tick();
    await tick();
    expect(reads()).toBe(before + 2);
  });
});

describe("Contact support under the bot answer", () => {
  async function askBot(q: string) {
    const box = await screen.findByPlaceholderText("Ask a question…");
    await userEvent.type(box, `${q}{Enter}`);
    await waitFor(() => expect(screen.getAllByText("Not supported yet.").length).toBeGreaterThan(0));
  }

  it("shows only under the latest answer and opens Support with the question, unsent", async () => {
    await openHelp();
    await screen.findByRole("button", { name: "Support" });
    await askBot("first question");
    await askBot("can I bulk tag fans?");
    expect(screen.getAllByRole("button", { name: "Contact support" })).toHaveLength(1);
    const turns = screen.getAllByText("Not supported yet.");
    const last = turns[turns.length - 1].closest(".flex.flex-col.gap-2") as HTMLElement;
    expect(last.querySelector("button")?.textContent).toContain("Contact support");
    await userEvent.click(screen.getByRole("button", { name: "Contact support" }));
    const box = await screen.findByRole("textbox", { name: "Message Support" });
    expect(box).toHaveValue("can I bulk tag fans?");
    expect(relayPost).not.toHaveBeenCalledWith("/admin/support/messages", expect.anything());
    await userEvent.type(box, " thanks");
    await userEvent.click(screen.getByRole("button", { name: "Back to help" }));
    await userEvent.click(screen.getByRole("button", { name: "Contact support" }));
    expect(await screen.findByRole("textbox", { name: "Message Support" })).toHaveValue("can I bulk tag fans? thanks\ncan I bulk tag fans?");
  });

  it("is hidden when Support is not configured", async () => {
    hub.configured = false;
    await openHelp();
    await askBot("anything");
    expect(screen.queryByRole("button", { name: "Contact support" })).toBeNull();
  });
});
