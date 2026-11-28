import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonRes, renderWithProviders, settled } from "@/test-utils";
import type { FeatureFlags } from "@/lib/appliedSettings";

const nav = vi.hoisted(() => ({ path: "/fansly-manager/home", search: "", push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.path,
  useSearchParams: () => new URLSearchParams(nav.search),
  useRouter: () => ({ push: nav.push, replace: nav.replace }),
}));
let flags: FeatureFlags | undefined;
vi.mock("@/components/shell/useFlags", () => ({ useFlags: () => flags }));
let granted: Set<string> | null = null;
vi.mock("@/components/shell/useGrantedPages", () => ({ useGrantedPages: () => granted }));
vi.mock("@/lib/fansly-mirror-pages", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/fansly-mirror-pages")>(),
  FANSLY_MIRROR_SECTIONS: {
    home: { index: "", pages: { "": "Home" } },
    lists: { index: "", pages: { "": "Lists", list: "List" } },
  },
}));
type Acct = { id: string; nickname: string; platform: string; is_active: boolean; has_session: boolean; session_dead_at?: string | null };
const acct = (id: string, nickname: string, platform = "fansly", dead = false): Acct =>
  ({ id, nickname, platform, is_active: true, has_session: true, session_dead_at: dead ? "2026-11-20T00:00:00Z" : null });
let accounts: Acct[] = [];
let status: "ok" | "pending" | "error" = "ok";
vi.mock("@/hooks/useAccounts", () => ({
  useAccounts: () => ({ isSuccess: status === "ok", isError: status === "error", data: status === "ok" ? { accounts, watchers: [] } : undefined }),
  usePlatformAccounts: (on: string) => accounts.filter((a) => a.platform === on),
  useAccountLabel: (id: string | null) => accounts.find((a) => a.id === id)?.nickname ?? id ?? "",
}));

import { FanslyMirrorChrome } from "./FanslyMirrorChrome";
import { FanslyMirrorFrame } from "./FanslyMirrorFrame";

const ME: Record<string, { username: string; name: string; avatar: string }> = {
  fa: { username: "ava_test", name: "Ava Test", avatar: "https://cdn.example.invalid/a.jpg" },
  fb: { username: "bea_test", name: "Bea Test", avatar: "https://cdn.example.invalid/b.jpg" },
};
const meFor = (init?: RequestInit) => new Headers(init?.headers).get("X-Account-Id") ?? "";
let meStatus: Record<string, number> = {};
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  flags = { fansly_manager: true, leak_tracker: false };
  granted = null;
  status = "ok";
  accounts = [acct("of1", "Olive OF", "onlyfans"), acct("fa", "Ava nick"), acct("fb", "Bea nick")];
  nav.path = "/fansly-manager/home";
  nav.search = "";
  meStatus = {};
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith("/api/of/v2/users/me")) {
      const id = meFor(init);
      return meStatus[id] ? jsonRes({ detail: "forbidden" }, meStatus[id]) : jsonRes(ME[id] ?? {});
    }
    return jsonRes({ detail: "unmocked" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  nav.push.mockClear();
  nav.replace.mockClear();
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
});

const SRC = "/fansly-mirror/pages/home/index.html";
const PAGE = `<head></head><body><div data-oi-nav>rail</div><h1 class="who">Your Model @yourmodel</h1><img data-oi-avatar src="data:,"></body>`;
const chrome = () =>
  renderWithProviders(
    <FanslyMirrorChrome>
      <FanslyMirrorFrame src={SRC} title="Homepage: Home" />
    </FanslyMirrorChrome>,
  );
const loadFrame = () => {
  const frame = screen.getByTitle("Homepage: Home") as HTMLIFrameElement;
  const doc = frame.contentDocument!;
  if (!doc.documentElement) doc.appendChild(doc.createElement("html"));
  doc.documentElement.innerHTML = PAGE;
  Object.defineProperty(doc, "readyState", { value: "complete", configurable: true });
  act(() => { frame.dispatchEvent(new Event("load")); });
  return doc;
};
const meReads = () => fetchMock.mock.calls.filter(([u]) => String(u).startsWith("/api/of/v2/users/me"));

describe("FanslyMirrorChrome", () => {
  it("heads a mirror page with its nav label over the frame", () => {
    nav.search = "creator=fa";
    chrome();
    expect(screen.getByRole("heading", { name: "Homepage" })).toBeInTheDocument();
    expect(screen.getByTitle("Homepage: Home")).toHaveAttribute("src", SRC);
  });

  it("with the flag off a mirror URL is not available, has no frame and reads nothing", () => {
    flags = { fansly_manager: false, leak_tracker: false };
    const { container } = chrome();
    expect(screen.getByText("Homepage is not available.")).toBeInTheDocument();
    expect(container.querySelector("iframe")).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("waits for the flags rather than flash not available: placeholder rows, no frame", () => {
    flags = undefined;
    const { container } = chrome();
    expect(container.querySelectorAll("[data-loading]").length).toBeGreaterThan(0);
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("waits for the accounts rather than flash no creator: placeholder rows, no frame", () => {
    status = "pending";
    const { container } = chrome();
    expect(container.querySelectorAll("[data-loading]").length).toBeGreaterThan(0);
    expect(container.querySelector("iframe")).toBeNull();
    expect(screen.queryByText(/tied a creator/)).toBeNull();
  });

  it("a failed accounts load shows the page with its placeholders, not a skeleton or no creator", () => {
    status = "error";
    renderWithProviders(<FanslyMirrorChrome><p>Mirror body</p></FanslyMirrorChrome>);
    expect(screen.getByText("Mirror body")).toBeInTheDocument();
    expect(screen.queryByText(/tied a creator/)).toBeNull();
    expect(screen.queryByTestId("fansly-standin-hint")).toBeNull();
  });

  it.each(["/fansly-manager/lists", "/fansly-manager", "/fansly-manager/nope"])("passes %s through as it is, flag or not", (path) => {
    nav.path = path;
    flags = { fansly_manager: false, leak_tracker: false };
    renderWithProviders(<FanslyMirrorChrome><p>Built body</p></FanslyMirrorChrome>);
    expect(screen.getByText("Built body")).toBeInTheDocument();
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("a mirror subpage under a Built section is chromed", () => {
    nav.path = "/fansly-manager/lists/list";
    renderWithProviders(<FanslyMirrorChrome><p>Mirror body</p></FanslyMirrorChrome>);
    expect(screen.getByRole("heading", { name: "Lists" })).toBeInTheDocument();
  });

  it("a live Fansly pick shows that creator with no hint", async () => {
    nav.search = "creator=fb";
    chrome();
    expect(screen.getByRole("combobox", { name: "Creator" })).toHaveTextContent("Bea nick");
    await settled();
    expect(screen.queryByText(/pick a model to switch/)).toBeNull();
  });

  it.each([
    ["no pick", ""],
    ["an unknown id", "creator=nope"],
    ["an OnlyFans creator", "creator=of1"],
  ])("with %s the first live Fansly creator stands in, with the hint", async (_, search) => {
    nav.search = search;
    chrome();
    expect(await screen.findByText("Showing Ava Test, pick a model to switch")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Creator" })).toHaveTextContent("Ava nick");
  });

  it("a dead first Fansly creator never stands in", async () => {
    accounts = [acct("fdead", "Dead nick", "fansly", true), acct("fb", "Bea nick")];
    nav.search = "creator=fdead";
    chrome();
    expect(await screen.findByText("Showing Bea Test, pick a model to switch")).toBeInTheDocument();
  });

  it("the picker lists only live Fansly creators and writes ?creator= with router.replace", () => {
    accounts = [...accounts, acct("fdead", "Dead nick", "fansly", true)];
    nav.search = "creator=fa&tab=2";
    window.history.replaceState(null, "", `${nav.path}?${nav.search}`);
    chrome();
    fireEvent.click(screen.getByRole("combobox", { name: "Creator" }));
    expect(within(screen.getByRole("listbox")).getAllByRole("option")).toHaveLength(2);
    expect(within(screen.getByRole("listbox")).queryByRole("option", { name: /Dead nick/ })).toBeNull();
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: /Bea nick/ }));
    expect(nav.replace).toHaveBeenCalledWith("/fansly-manager/home?creator=fb&tab=2", { scroll: false });
  });

  it("with no live Fansly creator: the no-creator state links to Creators Management, no frame", () => {
    accounts = [acct("of1", "Olive OF", "onlyfans"), acct("fdead", "Dead nick", "fansly", true)];
    const { container } = chrome();
    expect(screen.getByText(/You have not yet tied a creator/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Link account" })).toHaveAttribute("href", "/creators");
    expect(container.querySelector("iframe")).toBeNull();
    expect(meReads()).toHaveLength(0);
  });

  it("with no live Fansly creator and no Creators grant: the no-permission line", () => {
    accounts = [];
    granted = new Set(["/of-manager/home"]);
    chrome();
    expect(screen.getByText(/you don't have permission for this page/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Link account" })).toBeNull();
  });

  it("the frame shows the picked creator's identity", async () => {
    nav.search = "creator=fb";
    chrome();
    const doc = loadFrame();
    await waitFor(() => expect(doc.querySelector(".who")!.textContent).toBe("Bea Test @bea_test"));
    expect(doc.querySelector("img[data-oi-avatar]")!.getAttribute("src")).toContain("account_id=fb");
    expect(doc.documentElement.classList.contains("bright-theme")).toBe(document.documentElement.getAttribute("data-theme") === "light");
  });

  it("the frame follows the app theme on toggle, both ways", async () => {
    nav.search = "creator=fb";
    const before = document.documentElement.getAttribute("data-theme");
    document.documentElement.setAttribute("data-theme", "dark");
    try {
      chrome();
      const doc = loadFrame();
      expect(doc.documentElement.classList.contains("bright-theme")).toBe(false);
      act(() => { document.documentElement.setAttribute("data-theme", "light"); });
      await waitFor(() => expect(doc.documentElement.classList.contains("bright-theme")).toBe(true));
      act(() => { document.documentElement.setAttribute("data-theme", "dark"); });
      await waitFor(() => expect(doc.documentElement.classList.contains("bright-theme")).toBe(false));
    } finally {
      if (before === null) document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", before);
    }
  });

  it("a failed /users/me (403) keeps the placeholders and never shows another creator", async () => {
    meStatus = { fb: 403 };
    nav.search = "creator=fb";
    const { queryClient } = chrome();
    queryClient.setQueryData(["of-me", "fa"], ME.fa);
    const doc = loadFrame();
    await waitFor(() => expect(meReads().length).toBeGreaterThan(0));
    await settled();
    expect(meReads().every(([, init]) => meFor(init) === "fb")).toBe(true);
    expect(doc.querySelector(".who")!.textContent).toBe("Your Model @yourmodel");
    expect(doc.querySelector("img[data-oi-avatar]")!.getAttribute("src")).toBe("data:,");
    expect(doc.body.innerHTML + document.body.innerHTML).not.toMatch(/ava_test|Ava Test|account_id=fa/);
  });
});

describe("FanslyMirrorFrame", () => {
  const mount = (creator: string) => {
    nav.search = `creator=${creator}`;
    const utils = renderWithProviders(<FanslyMirrorFrame src={SRC} title="Homepage: Home" />);
    const frame = screen.getByTitle("Homepage: Home") as HTMLIFrameElement;
    act(() => { frame.dispatchEvent(new Event("load")); });
    const doc = frame.contentDocument!;
    if (!doc.documentElement) doc.appendChild(doc.createElement("html"));
    const click = (href: string, init: MouseEventInit = {}) => {
      doc.documentElement.innerHTML = `<body><a href="${href}"><span>go</span></a></body>`;
      const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ...init });
      doc.querySelector("span")!.dispatchEvent(ev);
      return ev;
    };
    return { ...utils, frame, click };
  };

  it("a plain left click on an in-frame /fansly-manager/ link moves the app, keeping the picked creator", () => {
    const { click } = mount("fb");
    expect(click("/fansly-manager/home").defaultPrevented).toBe(true);
    expect(nav.push).toHaveBeenCalledWith("/fansly-manager/home?creator=fb");
  });

  it("with no valid pick the link carries the stand-in", () => {
    const { click } = mount("nope");
    click("/fansly-manager/lists/list");
    expect(nav.push).toHaveBeenCalledWith("/fansly-manager/lists/list?creator=fa");
  });

  it("a # click does nothing", () => {
    const { click } = mount("fb");
    expect(click("#").defaultPrevented).toBe(true);
    expect(nav.push).not.toHaveBeenCalled();
  });

  it.each([{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }])("a modified click %o is left to the browser", (init) => {
    const { click } = mount("fb");
    expect(click("/fansly-manager/home", init).defaultPrevented).toBe(false);
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("a link outside /fansly-manager is left to the browser", () => {
    const { click } = mount("fb");
    expect(click("/fansly-mirror/static/x.css").defaultPrevented).toBe(false);
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("a creator switch remounts the frame", () => {
    const { frame, rerender } = mount("fa");
    rerender(<FanslyMirrorFrame src={SRC} title="Homepage: Home" />);
    expect(screen.getByTitle("Homepage: Home")).toBe(frame);
    nav.search = "creator=fb";
    rerender(<FanslyMirrorFrame src={SRC} title="Homepage: Home" />);
    expect(screen.getByTitle("Homepage: Home")).not.toBe(frame);
  });
});
