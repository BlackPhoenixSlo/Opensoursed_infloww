import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import { EXTRA_LABEL, EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";

vi.mock("@/lib/relay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/relay")>()),
  relay: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
let me: { is_admin?: boolean } | null;
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: me, loading: false }) }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(window.location.search),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));

import Page from "@/app/creators/page";
import { relay, RelayError } from "@/lib/relay";
const relayGet = relay.get as unknown as Mock;
const relayPut = relay.put as unknown as Mock;

const PROBE_URL = "chrome-extension://anjjmiahkfondbhahocpkehjjabkommc/icons/icon16.png";

type Acct = { id: string; nickname?: string; platform?: "onlyfans" | "fansly"; has_session?: boolean; session_dead_at?: string; session_dead_reason?: string };
let accounts: Acct[];
let health: () => Promise<unknown>;
let proxies: () => Promise<unknown>;
let employees: () => Promise<unknown>;
let liveRev: unknown;
let settings: Record<string, unknown> | null;
let fetchMock: Mock;

beforeEach(() => {
  me = { is_admin: false };
  accounts = [];
  health = () => Promise.resolve({ ok: true, accounts: [] });
  proxies = () => Promise.resolve({ proxies: [], pool: { size: 0, account_ids: [] }, accounts: [] });
  employees = () => Promise.resolve({ employees: [] });
  liveRev = { live_rev: "rev-1" };
  settings = { language: "en" };
  relayPut.mockReset();
  relayPut.mockImplementation((path: string, body: Record<string, unknown>) => {
    if (path === "/admin/settings/account") { settings = body; return Promise.resolve({ tab: "account", config: body }); }
    return Promise.resolve({});
  });
  relayGet.mockReset();
  relayGet.mockImplementation((path: string) => {
    if (path === "/admin/accounts") return Promise.resolve({ accounts, active_account_id: accounts[0]?.id ?? null });
    if (path === "/health?all_accounts=1") return health();
    if (path === "/admin/proxies") return proxies();
    if (path.startsWith("/admin/employees?")) return employees();
    if (path === "/admin/rev/live") return Promise.resolve(liveRev);
    if (path === "/admin/users/llm-key-status") return Promise.resolve({ agencies: [] });
    if (path === "/admin/settings/account") {
      return settings ? Promise.resolve({ tab: "account", config: settings }) : Promise.reject(new RelayError(401, null, "relay 401"));
    }
    return Promise.resolve({});
  });
  fetchMock = vi.fn(() => Promise.reject(new TypeError("not installed")));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const table = () => screen.getByRole("table");
const rows = () => within(table()).getAllByRole("row").slice(1);
const rowOf = (name: string) => rows().find((r) => within(r).queryAllByText(name).length > 0)!;
const connCell = (name: string) => {
  const i = within(table()).getAllByRole("columnheader").findIndex((h) => h.textContent === "Connectivity status");
  return within(rowOf(name)).getAllByRole("cell")[i];
};
const follows = (a: Node, b: Node) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
const extrasOf = (name: string) => within(rowOf(name)).getAllByRole("cell")[1].querySelector("[title]")?.getAttribute("title") ?? "";

describe("/creators — the creator table leads", () => {
  it("renders the table before any capture form, with the capture's column headers in order", async () => {
    accounts = [{ id: "acct-a", nickname: "Alpha", has_session: true }];
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Manage creators");
    const headers = within(table()).getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual([
      "",
      "Creator",
      "Nickname",
      "Tag",
      "Account",
      "Creator ID",
      "Employees",
      "Connectivity status",
      "Action",
    ]);
    for (const h of headers) expect(h).toHaveClass("bg-panel", "text-white");
    expect(headers[headers.length - 1]).toHaveClass("border-l", "border-[#2c2c2c]");
    expect(screen.getByRole("button", { name: "Add creator" })).toHaveClass("bg-cta", "text-black");

    for (const form of ["Paste cURL", /^Connect Fansly/]) {
      expect(screen.queryByRole("heading", { name: form })).toBeNull();
    }
    const gear = within(table()).getByRole("button", { name: "Tag settings" });
    await waitFor(() => expect(gear).toHaveAttribute("title", "Tag settings"));
    expect(gear).toBeEnabled();
  });

  it("fills a row from the existing reads: nickname, platform, Creator ID and bound proxy", async () => {
    accounts = [{ id: "acct-f", nickname: "Foxtrot", platform: "fansly", has_session: true }];
    proxies = () => Promise.resolve({ proxies: [{ label: "px-1", scheme: "http", host: "10.0.0.1", port: 8000, assigned_account_ids: ["acct-f"] }], pool: { size: 0, account_ids: [] }, accounts: [] });
    renderWithProviders(<Page />);
    await screen.findAllByText("Foxtrot");
    const row = rowOf("Foxtrot");
    expect(within(row).getByText("Fansly")).toBeInTheDocument();
    expect(extrasOf("Foxtrot")).toContain("acct-f");
    expect(extrasOf("Foxtrot").startsWith(EXTRA_LABEL)).toBe(true);
    await waitFor(() => expect(extrasOf("Foxtrot")).toContain("Custom proxy · px-1"));
    const paths = new Set(relayGet.mock.calls.map(([p]) => String(p)));
    for (const p of paths) {
      expect([
        "/admin/accounts", "/health?all_accounts=1", "/admin/proxies", "/admin/employees?include_disabled=false",
        "/admin/rev/live", "/admin/my-llm-keys", "/admin/settings/account",
      ]).toContain(p);
    }
  });


  it("fills Creator ID with the stored account id (the OF user id), not the /users/me @username", async () => {
    accounts = [{ id: "acct-o", nickname: "Oscar", platform: "onlyfans", has_session: true }];
    const base = relayGet.getMockImplementation()!;
    relayGet.mockImplementation((path: string, opts?: unknown) =>
      path === "/api/of/v2/users/me" ? Promise.resolve({ id: "acct-o", username: "oscar_of", avatar: null }) : base(path, opts));
    renderWithProviders(<Page />);
    await screen.findAllByText("Oscar");
    const i = within(table()).getAllByRole("columnheader").findIndex((h) => h.textContent === "Creator ID");
    await waitFor(() => expect(within(rowOf("Oscar")).getAllByRole("cell")[i]).toHaveTextContent(/^acct-o$/));
    expect(within(rowOf("Oscar")).getByText("OnlyFans")).toBeInTheDocument();
    expect(within(rowOf("Oscar")).getByText("default")).toBeInTheDocument();
  });
});

describe("/creators — the filter bar narrows the table", () => {
  const names = () => rows().map((r) => within(r).getAllByRole("cell")[1].textContent);
  const filter = (name: string) => screen.getByRole("combobox", { name });
  const search = () => screen.getByRole("textbox", { name: "Creator name" });
  const listOf = (el: HTMLElement) => document.getElementById(el.getAttribute("list") ?? "");
  const pick = (name: string, label: string) => {
    const el = filter(name);
    const list = listOf(el);
    if (list) { fireEvent.change(el, { target: { value: label } }); return; }
    const opt = within(el).getAllByRole("option").find((o) => o.textContent === label)!;
    fireEvent.change(el, { target: { value: (opt as HTMLOptionElement).value } });
  };
  const roster = () => {
    accounts = [
      { id: "acct-1", nickname: "Alpha", platform: "onlyfans", has_session: true },
      { id: "acct-2", nickname: "Bravo", platform: "fansly", has_session: true },
      { id: "acct-3", nickname: "Charlie", platform: "onlyfans", has_session: true, session_dead_at: "2026-07-10T14:14:37Z", session_dead_reason: "no_session" },
      { id: "acct-4", nickname: "Delta", platform: "onlyfans", has_session: false },
    ];
    health = () => Promise.resolve({
      ok: true,
      accounts: [
        { account_id: "acct-1", ok: true },
        { account_id: "acct-2", ok: false, error: "auth_failed" },
        { account_id: "acct-3", ok: true },
        { account_id: "acct-4", ok: false, error: "no_session" },
      ],
    });
    employees = () => Promise.resolve({
      employees: [
        { id: 1, display_name: "Emp One", color: null, is_active: true, account_ids: ["acct-2"], chatter_id: "c1" },
        { id: 2, display_name: "Emp Two", color: null, is_active: true, account_ids: null, chatter_id: "c2" },
      ],
    });
  };
  const ALL = ["Alpha", "Bravo", "Charlie", "Delta"];

  it("draws the capture's six filters in its order, with its options, and no Reset", async () => {
    roster();
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");
    const bar = screen.getByRole("search", { name: "Filter creators" });
    const controls = [within(bar).getByRole("textbox"), ...within(bar).getAllByRole("combobox")];
    expect(follows(controls[0], controls[1])).toBe(true);
    expect(controls.map((c) => c.getAttribute("aria-label"))).toEqual([
      "Creator name",
      "Platform",
      "Tag",
      "Connectivity status",
      "Employee",
      "Account status",
    ]);
    expect(search()).toHaveAttribute("maxLength", "50");
    const opts = (name: string) => within(filter(name)).getAllByRole("option").map((o) => o.textContent);
    const searchable = (name: string) => [...(listOf(filter(name))?.querySelectorAll("option") ?? [])].map((o) => o.value);
    expect(opts("Platform")).toEqual(["Platform", "OnlyFans", "Fansly"]);
    expect(opts("Connectivity status")).toEqual([
      "Connectivity status", "Connected", "Disconnected", "Not connected", "Pending connection", "2FA required",
    ]);
    await waitFor(() => expect(searchable("Employee")).toEqual(["Emp One", "Emp Two"]));
    expect(filter("Employee")).toHaveAttribute("placeholder", "Employee");
    expect(opts("Account status")).toEqual(["Account status", "Activated", "Deactivated"]);
    expect(within(bar).queryByRole("button")).toBeNull();
    for (const c of controls) expect(c).toHaveClass("bg-[#161616]", "border-0");
  });

  it("disables Tag as Not wired when the profile read is refused; Account status stays live", async () => {
    roster();
    settings = null;
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");
    expect(filter("Tag")).toBeDisabled();
    expect(filter("Tag")).toHaveAttribute("title", "not wired");
    expect(filter("Account status")).toBeEnabled();
  });

  it("filters by the Tags the account details hold, and shows each row's Creator name, Tag and image", async () => {
    roster();
    settings = { creators: { profiles: {
      "acct-1": { name: "Alpha Creator", tag: "VIP", avatar: "data:image/jpeg;base64,AA" },
      "acct-3": { tag: "New" },
    } } };
    renderWithProviders(<Page />);
    await waitFor(() => expect(filter("Tag")).toBeEnabled());
    expect(within(filter("Tag")).getAllByRole("option").map((o) => o.textContent)).toEqual(["Tag", "New", "VIP"]);
    expect(within(rowOf("Alpha Creator")).getByText("VIP")).toBeInTheDocument();
    expect(rowOf("Alpha Creator").querySelector("img")).toHaveAttribute("src", "data:image/jpeg;base64,AA");
    pick("Tag", "VIP");
    expect(names()).toEqual(["Alpha Creator"]);
    pick("Tag", "New");
    expect(names()).toEqual(["Charlie"]);
    pick("Tag", "Tag");
    expect(names()).toEqual(["Alpha Creator", "Bravo", "Charlie", "Delta"]);
  });

  it("joins a row's Employees with \", \" and keeps the full list on hover past the two-line clamp", async () => {
    roster();
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");
    const i = within(table()).getAllByRole("columnheader").findIndex((h) => h.textContent === "Employees");
    const cell = (name: string) => within(rowOf(name)).getAllByRole("cell")[i].firstElementChild!;
    await waitFor(() => expect(cell("Bravo")).toHaveTextContent("Emp One, Emp Two"));
    expect(cell("Bravo")).toHaveAttribute("title", "Emp One, Emp Two");
    expect(cell("Alpha")).toHaveAttribute("title", "Emp Two");
  });

  it("narrows by search, platform, connectivity and employee, and each filter clears on its own", async () => {
    roster();
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Alpha")).toHaveTextContent("Connected"));
    expect(names()).toEqual(ALL);

    fireEvent.change(search(), { target: { value: "rav" } });
    expect(names()).toEqual(ALL);
    fireEvent.keyDown(search(), { key: "Enter" });
    expect(names()).toEqual(["Bravo"]);
    fireEvent.change(search(), { target: { value: "ACCT-4" } });
    expect(names()).toEqual(["Bravo"]);
    fireEvent.keyDown(search(), { key: "Enter" });
    expect(names()).toEqual(["Delta"]);
    fireEvent.change(search(), { target: { value: "" } });
    fireEvent.keyDown(search(), { key: "Enter" });
    expect(names()).toEqual(ALL);

    pick("Platform", "Fansly");
    expect(names()).toEqual(["Bravo"]);
    pick("Platform", "OnlyFans");
    expect(names()).toEqual(["Alpha", "Charlie", "Delta"]);
    pick("Platform", "Platform");
    expect(names()).toEqual(ALL);

    pick("Connectivity status", "Disconnected");
    expect(names()).toEqual(["Bravo", "Charlie"]);
    pick("Connectivity status", "Connected");
    expect(names()).toEqual(["Alpha"]);
    pick("Connectivity status", "Not connected");
    expect(names()).toEqual(["Delta"]);
    pick("Connectivity status", "2FA required");
    expect(screen.getByText("No data")).toBeInTheDocument();
    expect(screen.queryByText(/^Total:/)).toBeNull();
    pick("Connectivity status", "Connectivity status");

    await waitFor(() => expect(listOf(filter("Employee"))?.querySelectorAll("option")).toHaveLength(2));
    fireEvent.change(filter("Employee"), { target: { value: "one" } });
    expect(names()).toEqual(ALL);
    pick("Employee", "Emp One");
    expect(names()).toEqual(["Bravo"]);
    expect(screen.getByText("Total: 1 creators")).toBeInTheDocument();
    pick("Employee", "Emp Two");
    expect(names()).toEqual(ALL);
    pick("Employee", "Emp One");
    fireEvent.change(filter("Employee"), { target: { value: "" } });
    expect(names()).toEqual(ALL);

    pick("Platform", "OnlyFans");
    pick("Connectivity status", "Disconnected");
    fireEvent.change(search(), { target: { value: "char" } });
    fireEvent.keyDown(search(), { key: "Enter" });
    expect(names()).toEqual(["Charlie"]);
    pick("Connectivity status", "Connectivity status");
    expect(names()).toEqual(["Charlie"]);
    fireEvent.change(search(), { target: { value: "" } });
    fireEvent.keyDown(search(), { key: "Enter" });
    pick("Platform", "Platform");
    for (const name of ["Platform", "Connectivity status", "Employee"]) expect(filter(name)).toHaveValue("");
    expect(names()).toEqual(ALL);
    expect(screen.getByText("Total: 4 creators")).toBeInTheDocument();
  });

  it("leaves the connectivity filter Not wired when the health read failed", async () => {
    roster();
    health = () => Promise.reject(new RelayError(500, null, "relay 500"));
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Alpha")).toHaveTextContent("—"));
    expect(filter("Connectivity status")).toBeDisabled();
    expect(filter("Connectivity status")).toHaveAttribute("title", "not wired");
    expect(names()).toEqual(ALL);
  });
});

describe("/creators — Add creator: Browser login first, Extension second", () => {
  const relayPost = relay.post as unknown as Mock;
  const relayPatch = relay.patch as unknown as Mock;
  const dialog = () => screen.getByRole("dialog");
  const open = async () => {
    fireEvent.click(await screen.findByRole("button", { name: "Add creator" }));
    return screen.getByRole("dialog", { name: "Add creator" });
  };
  const btn = (name: string | RegExp) => within(dialog()).getByRole("button", { name });
  const choice = (name: "Browser login" | "Extension") => within(dialog()).getByRole("radio", { name: new RegExp(`^${name}`) });
  const CREATOR_NAME = "Creator draft";
  const enterLogin = () => {
    expect(btn("Next")).toBeDisabled();
    fireEvent.change(within(dialog()).getByLabelText("Creator name"), { target: { value: CREATOR_NAME } });
    fireEvent.change(within(dialog()).getByLabelText("Gender"), { target: { value: "Female" } });
    expect(btn("Next")).toBeEnabled();
    fireEvent.click(btn("Next"));
    const platform = within(dialog()).getByRole("radiogroup", { name: "Platform" });
    expect(within(platform).getByRole("radio", { name: "OnlyFans" })).toBeChecked();
    expect(within(platform).getByRole("radio", { name: "Fansly" })).toBeEnabled();
    fireEvent.click(btn("Next"));
    expect(within(dialog()).getByRole("radiogroup", { name: "Login method" })).toBeInTheDocument();
  };
  const toExtension = async () => {
    await open();
    enterLogin();
    fireEvent.click(choice("Extension"));
    return within(dialog()).getByRole("region", { name: "Extension" });
  };
  const CURL = "curl 'https://onlyfans.com/api2/v2/x' -b 'sess=1' -A 'UA'";
  const bootstrap = (paste: HTMLElement) => {
    fireEvent.change(within(paste).getByLabelText("Copied cURL"), { target: { value: CURL } });
    fireEvent.click(btn("Link account"));
  };
  beforeEach(() => {
    relayPost.mockReset();
    relayPatch.mockReset();
    relayPost.mockResolvedValue({});
    relayPatch.mockResolvedValue({});
  });

  it("sits in the page header, enters details and platform, then Browser login (recommended) first, Extension second", async () => {
    accounts = [{ id: "acct-a", nickname: "Alpha", has_session: true }];
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");

    const add = within(screen.getByRole("banner")).getByRole("button", { name: "Add creator" });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(add);
    const d = screen.getByRole("dialog", { name: "Add creator" });
    expect(within(d).queryByRole("radiogroup", { name: "Login method" })).toBeNull();
    enterLogin();
    const group = within(d).getByRole("radiogroup", { name: "Login method" });
    const radios = within(group).getAllByRole("radio");
    expect(radios).toHaveLength(2);
    expect(radios[0]).toHaveAccessibleName(/^Browser login\s*Recommended/);
    expect(radios[1]).toHaveAccessibleName(/^Extension\s*If browser login doesn't work/);
    expect(radios[0]).toBeChecked();
    const bb = within(d).getByRole("region", { name: "Browserbase login" });
    expect(within(bb).getByLabelText("OnlyFans email")).toBeInTheDocument();
    expect(within(d).queryByRole("region", { name: "Extension" })).toBeNull();
    expect(within(d).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(within(d).getByRole("button", { name: "Start browser login" })).toBeDisabled();
    expect(follows(within(d).getByRole("button", { name: "Cancel" }), within(d).getByRole("button", { name: "Start browser login" }))).toBe(true);
    expect(within(d).queryByLabelText("Creator name")).toBeNull();
    expect(within(d).queryByText("Proxy selection")).toBeNull();
    expect(within(d).queryByRole("combobox")).toBeNull();
    expect(within(d).queryByText(/Still unable/)).toBeNull();
    expect(within(d).queryByRole("button", { name: /Try Browserbase login|How it works|Next/ })).toBeNull();
    expect(within(d).getByRole("button", { name: "Link a Fansly account instead" })).toBeInTheDocument();

    fireEvent.click(d.parentElement!);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(within(d).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await open();
    fireEvent.click(btn("Cancel"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the Extension choice swaps the panel and the footer button, and back", async () => {
    renderWithProviders(<Page />);
    const paste = await toExtension();
    expect(choice("Extension")).toBeChecked();
    expect(within(dialog()).queryByRole("region", { name: "Browserbase login" })).toBeNull();
    expect(within(paste).getByText(/Open the extension, click Copy cURL/)).toBeInTheDocument();
    expect(btn("Link account")).toBeDisabled();
    expect(within(dialog()).queryByRole("button", { name: "Start browser login" })).toBeNull();
    expect(within(paste).queryByRole("combobox")).toBeNull();
    expect(within(paste).queryByLabelText("Nickname")).toBeNull();
    expect(within(paste).queryByRole("link", { name: /Download app/ })).toBeNull();
    expect(within(paste).getByText("Troubleshooting").closest("details")).not.toHaveAttribute("open");
    fireEvent.change(within(paste).getByLabelText("Copied cURL"), { target: { value: CURL } });
    expect(btn("Link account")).toBeEnabled();
    fireEvent.click(choice("Browser login"));
    expect(within(dialog()).getByRole("region", { name: "Browserbase login" })).toBeInTheDocument();
    expect(within(dialog()).queryByRole("button", { name: "Link account" })).toBeNull();
  });

  const poolRelay = (assignError?: Error, reloadFailures = 0) => {
    const onPool: string[] = [];
    proxies = () => Promise.resolve({
      proxies: [{ label: "px-1", scheme: "http", host: "10.0.0.1", port: 8000, assigned_account_ids: [] }],
      pool: { size: 3, account_ids: [...onPool] }, accounts: [],
    });
    relayPost.mockImplementation((path: string, body?: { account_id?: string }) => {
      if (path === "/admin/session/bootstrap") {
        return Promise.resolve({ account_id: "acct-new", user_id: 7, session_file: "s.json", x_of_rev: "rev-1" });
      }
      if (path === "/admin/proxy-pool/assign") {
        if (assignError) return Promise.reject(assignError);
        if (!onPool.includes(body!.account_id!)) onPool.push(body!.account_id!);
      }
      if (path.startsWith("/admin/reload-session") && reloadFailures > 0) {
        reloadFailures -= 1;
        return Promise.reject(new Error("relay 500"));
      }
      return Promise.resolve({ ok: true });
    });
  };

  it("Browser login starts with no proxy picked: the relay assigns one itself", async () => {
    poolRelay();
    renderWithProviders(<Page />);
    await open();
    enterLogin();
    const bb = within(dialog()).getByRole("region", { name: "Browserbase login" });
    expect(within(bb).getByText(/^Proxy assigned automatically/)).toBeInTheDocument();
    fireEvent.change(within(bb).getByLabelText("OnlyFans email"), { target: { value: "a@b.c" } });
    fireEvent.change(within(bb).getByLabelText("OnlyFans password"), { target: { value: "pw" } });
    fireEvent.click(btn("Start browser login"));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/login/remote/start", {
      email: "a@b.c", password: "pw", backend: "browserbase", proxy: undefined, nickname: CREATOR_NAME,
    }));
  });

  it("with a pool, the Extension binds a pool proxy after the capture, says so inline, and the linked step reads it", async () => {
    poolRelay();
    const confirm = vi.spyOn(window, "confirm");
    renderWithProviders(<Page />);
    const paste = await toExtension();
    await waitFor(() => expect(within(paste).getByText(/If this account has no proxy yet, Inflowwww's default proxy is assigned after linking/)).toBeInTheDocument());
    bootstrap(paste);
    await within(dialog()).findByText("Creator account is linked to Inflowwww");
    expect(confirm).not.toHaveBeenCalled();
    const posts = relayPost.mock.calls.map(([p]) => String(p));
    expect(posts.indexOf("/admin/proxy-pool/assign")).toBeGreaterThan(posts.indexOf("/admin/session/bootstrap"));
    expect(posts.indexOf("/admin/reload-session?account_id=acct-new")).toBeGreaterThan(posts.indexOf("/admin/proxy-pool/assign"));
    expect(relayPost).toHaveBeenCalledWith("/admin/proxy-pool/assign", { account_id: "acct-new" });
    expect(relayPost).not.toHaveBeenCalledWith("/admin/proxies/assign", expect.anything());
    expect(await within(dialog()).findByText("Inflowwww proxy")).toBeInTheDocument();
    confirm.mockRestore();
  });

  it("a failed pool attach is shown in the panel; Continue goes on and the linked step reads No proxy", async () => {
    poolRelay(new Error("no Inflowwww proxies are set up on this relay"));
    renderWithProviders(<Page />);
    const paste = await toExtension();
    await waitFor(() => expect(within(paste).getByText(/default proxy is assigned after linking/)).toBeInTheDocument());
    bootstrap(paste);
    expect(await within(paste).findByText(/but proxy attach failed:\s+no Inflowwww proxies are set up on this relay/)).toBeInTheDocument();
    expect(within(dialog()).queryByText("Creator account is linked to Inflowwww")).toBeNull();
    expect(relayPost).not.toHaveBeenCalledWith("/admin/reload-session?account_id=acct-new");
    fireEvent.click(within(paste).getByRole("button", { name: "Continue" }));
    await within(dialog()).findByText("Creator account is linked to Inflowwww");
    expect(await within(dialog()).findByText("No proxy (server IP)")).toBeInTheDocument();
    expect(within(dialog()).queryByText("Inflowwww proxy")).toBeNull();
  });

  it("when the bind worked but the session reload failed, the panel says so and Retry finishes the attach", async () => {
    poolRelay(undefined, 1);
    renderWithProviders(<Page />);
    const paste = await toExtension();
    await waitFor(() => expect(within(paste).getByText(/default proxy is assigned after linking/)).toBeInTheDocument());
    bootstrap(paste);
    expect(await within(paste).findByText(/the proxy is attached, but reloading the session failed:\s+relay 500\s+Press Retry/)).toBeInTheDocument();
    fireEvent.click(within(paste).getByRole("button", { name: "Retry" }));
    await within(dialog()).findByText("Creator account is linked to Inflowwww");
    expect(relayPost.mock.calls.filter(([p]) => p === "/admin/reload-session?account_id=acct-new")).toHaveLength(2);
    expect(await within(dialog()).findByText("Inflowwww proxy")).toBeInTheDocument();
  });

  it("the linked step shows an error, not a cached proxy, when the proxies read fails", async () => {
    poolRelay();
    renderWithProviders(<Page />);
    const paste = await toExtension();
    await waitFor(() => expect(within(paste).getByText(/default proxy is assigned after linking/)).toBeInTheDocument());
    const before = proxies;
    proxies = () => relayPost.mock.calls.some(([p]) => p === "/admin/proxy-pool/assign")
      ? Promise.reject(new RelayError(500, null, "relay 500")) : before();
    bootstrap(paste);
    await within(dialog()).findByText("Creator account is linked to Inflowwww");
    expect(await within(dialog()).findByText("Couldn't read this account's proxy.")).toBeInTheDocument();
    expect(within(dialog()).queryByText("No proxy (server IP)")).toBeNull();
    expect(within(dialog()).queryByText("Inflowwww proxy")).toBeNull();
  });

  it("the Fansly link swaps to the Fansly paste session: Browser login off, Done beside Cancel", async () => {
    renderWithProviders(<Page />);
    await open();
    enterLogin();
    fireEvent.click(btn("Link a Fansly account instead"));
    expect(within(dialog()).getAllByRole("region").map((s) => s.getAttribute("aria-label"))).toEqual(["Fansly paste session"]);
    expect(choice("Browser login")).toBeDisabled();
    expect(choice("Extension")).toBeChecked();
    expect(btn("Done")).toBeInTheDocument();
    fireEvent.click(btn("Link an OnlyFans account instead"));
    expect(choice("Browser login")).toBeChecked();
    expect(within(dialog()).getByRole("region", { name: "Browserbase login" })).toBeInTheDocument();
  });

  it("runs the extension probe once on mount with the unchanged URL, and the Extension panel reads its result", async () => {
    fetchMock.mockImplementation(() => Promise.resolve({ ok: true }));
    renderWithProviders(<Page />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(PROBE_URL, { method: "GET", cache: "no-store" });

    const paste = await toExtension();
    await waitFor(() => expect(within(paste).getByText("Extension installed")).toBeInTheDocument());
    fireEvent.click(btn("Close"));
    await open();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows Install Chrome Extension when the probe found no extension", async () => {
    renderWithProviders(<Page />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const paste = await toExtension();
    await waitFor(() => expect(within(paste).getByRole("link", { name: "Install Chrome Extension" })).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("is reachable from the empty roster, and on a phone the Extension panel says to use Browser login", async () => {
    renderWithProviders(<Page />);
    await screen.findByText("No data");
    const paste = await toExtension();
    const body = within(paste).getByLabelText("Copied cURL").closest(".hidden")!;
    expect(body).toHaveClass("hidden", "md:block");
    const line = within(paste).getByText("The extension needs desktop Chrome. On a phone, use Browser login.");
    expect(line).toHaveClass("md:hidden");
    expect(body).not.toContainElement(line);
    expect(btn("Link account")).toHaveClass("max-md:hidden");
    fireEvent.click(choice("Browser login"));
    expect(within(dialog()).getByRole("region", { name: "Browserbase login" }).closest(".hidden")).toBeNull();
  });

  it("captures, then one linked screen: the account, its proxy and the account details; Done saves and closes", async () => {
    employees = () => Promise.resolve({
      employees: [
        { id: 1, display_name: "Emp One", color: null, is_active: true, account_ids: ["acct-x"], chatter_id: "c1" },
        { id: 2, display_name: "Emp Two", color: null, is_active: true, account_ids: null, chatter_id: "c2" },
      ],
    });
    relayPost.mockImplementation((path: string) =>
      path === "/admin/session/bootstrap"
        ? Promise.resolve({ account_id: "acct-new", user_id: 7, session_file: "s.json", x_of_rev: "rev-1" })
        : Promise.resolve({}),
    );
    renderWithProviders(<Page />);
    bootstrap(await toExtension());

    await within(dialog()).findByText("Creator account is linked to Inflowwww");
    expect(relayPost).toHaveBeenCalledWith("/admin/session/bootstrap", expect.objectContaining({ mode: "paste-curl" }));
    expect(await within(dialog()).findByText("No proxy (server IP)")).toBeInTheDocument();
    expect(relayPost).not.toHaveBeenCalledWith("/admin/proxy-pool/assign", expect.anything());
    expect(within(dialog()).queryByRole("radiogroup", { name: "Login method" })).toBeNull();
    expect(within(dialog()).getByText("Account details")).toBeInTheDocument();
    expect(within(dialog()).getByLabelText("Nickname")).toHaveValue(CREATOR_NAME);
    fireEvent.change(within(dialog()).getByLabelText("Nickname"), { target: { value: "Nova" } });
    fireEvent.change(within(dialog()).getByLabelText("Tag (Optional)"), { target: { value: "VIP" } });
    fireEvent.change(within(dialog()).getByLabelText("Internal notes (Optional)"), { target: { value: "night shift" } });
    fireEvent.click(btn("Assigned employees"));
    const list = within(dialog()).getByRole("listbox");
    expect(within(list).getByRole("option", { name: /Emp Two/ })).toBeDisabled();
    fireEvent.click(within(list).getByRole("option", { name: "Emp One" }));
    await waitFor(() => expect(btn("Done")).toBeEnabled());
    fireEvent.click(btn("Done"));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText("Creator added")).toBeInTheDocument();
    expect(relayPatch).toHaveBeenCalledWith("/admin/accounts/acct-new", { nickname: "Nova" });
    expect(relayPut).toHaveBeenCalledWith("/admin/employees/1/access", { account_ids: ["acct-x", "acct-new"] });
    expect((settings as { creators: { profiles: unknown } }).creators.profiles).toEqual({
      "acct-new": expect.objectContaining({ tag: "VIP", notes: "night shift" }),
    });
  });

  it("a Creator saved before (a draft) still opens from its row, and Edit and Delete still work", async () => {
    settings = { language: "en", creators: { drafts: [{ id: "d1", name: "Nova", gender: "Female", created_at: "2026-11-01T00:00:00Z" }] } };
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Nova")).toHaveTextContent("Pending connection"));

    fireEvent.click(within(rowOf("Nova")).getByRole("button", { name: "Link creator account" }));
    expect(within(screen.getByRole("dialog", { name: "Link creator account" })).getByRole("radiogroup", { name: "Login method" })).toBeInTheDocument();
    fireEvent.click(btn("Close"));

    fireEvent.click(within(rowOf("Nova")).getByRole("button", { name: "More actions for Nova" }));
    expect(within(screen.getByRole("menu")).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Edit", "Delete"]);
    fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "Delete" }));
    const del = screen.getByRole("dialog", { name: "Delete Nova" });
    fireEvent.click(within(del).getByRole("button", { name: "Delete creator" }));
    fireEvent.click(within(del).getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(screen.getByText("No data")).toBeInTheDocument());
    expect((settings as { creators: { drafts: unknown[] } }).creators.drafts).toEqual([]);
  });

  it("reads the proxies list under one query key with the modal open", async () => {
    const { queryClient } = renderWithProviders(<Page />);
    await open();
    await waitFor(() => expect(relayGet.mock.calls.filter(([p]) => p === "/admin/proxies")).toHaveLength(1));
    const keys = queryClient.getQueryCache().findAll({ queryKey: ["proxies"] }).map((q) => JSON.stringify(q.queryKey));
    expect(keys).toEqual([JSON.stringify(["proxies", "list"])]);
  });
});

describe("/creators — connectivity in the capture's words", () => {
  it("maps live, down, probing and no session, and a dead session outranks a live probe", async () => {
    accounts = [
      { id: "acct-dead", nickname: "Dead", has_session: true, session_dead_at: "2026-07-10T14:14:37Z", session_dead_reason: "no_session" },
      { id: "acct-live", nickname: "Live", has_session: true },
      { id: "acct-down", nickname: "Down", has_session: true },
      { id: "acct-slow", nickname: "Slow", has_session: true },
      { id: "acct-none", nickname: "None", has_session: false },
    ];
    health = () => Promise.resolve({
      ok: false,
      accounts: [
        { account_id: "acct-dead", ok: true },
        { account_id: "acct-live", ok: true },
        { account_id: "acct-down", ok: false, error: "auth_failed" },
        { account_id: "acct-slow", ok: false, error: "timeout", timed_out: true, message: "still running" },
        { account_id: "acct-none", ok: false, error: "no_session" },
      ],
    });
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Live")).toHaveTextContent("Connected"));

    expect(connCell("Dead")).toHaveTextContent(/^Disconnected/);
    expect(within(connCell("Dead")).getByText("automations paused")).toBeInTheDocument();
    expect(connCell("Down")).toHaveTextContent("Disconnected");
    expect(within(connCell("Down")).getByText("Disconnected")).toHaveAttribute("title", "auth_failed");
    expect(connCell("Slow")).toHaveTextContent("Pending connection");
    expect(connCell("None")).toHaveTextContent("Not connected");
  });

  it("shows Pending connection while the health read is in flight", async () => {
    accounts = [{ id: "acct-a", nickname: "Alpha", has_session: true }];
    health = () => new Promise(() => {});
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");
    expect(connCell("Alpha")).toHaveTextContent("Pending connection");
  });

  it("a failed health read leaves the cells — with the error as title, never Pending connection", async () => {
    accounts = [
      { id: "acct-a", nickname: "Alpha", has_session: true },
      { id: "acct-dead", nickname: "Dead", has_session: true, session_dead_at: "2026-07-10T14:14:37Z", session_dead_reason: "wrong_user" },
    ];
    health = () => Promise.reject(new RelayError(401, null, "relay 401"));
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Alpha")).toHaveTextContent("—"));
    expect(within(connCell("Alpha")).getByText("—")).toHaveAttribute("title", "relay 401");
    expect(within(table()).queryByText("Pending connection")).toBeNull();
    expect(connCell("Dead")).toHaveTextContent(/^Disconnected/);
  });
});

describe("/creators — the footer pages the table on the client", () => {
  it("shows the total and pages 10 / 20 / 50 per page", async () => {
    accounts = Array.from({ length: 23 }, (_, i) => ({ id: `acct-${i + 1}`, nickname: `Model ${i + 1}` }));
    renderWithProviders(<Page />);
    await screen.findAllByText("Model 1");

    expect(screen.getByText("Total: 23 creators")).toBeInTheDocument();
    expect(rows()).toHaveLength(10);
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Page 3" }));
    expect(rows()).toHaveLength(3);
    expect(screen.getAllByText("Model 21")[0]).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();

    const per = () => screen.getByRole("combobox", { name: "Per page" });
    const size = (n: string) => {
      fireEvent.click(per());
      fireEvent.click(within(screen.getByRole("listbox", { name: "Per page" })).getByRole("option", { name: n }));
    };
    fireEvent.click(per());
    expect(within(screen.getByRole("listbox", { name: "Per page" })).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["10", "20", "50"]);
    fireEvent.click(per());
    size("20");
    expect(rows()).toHaveLength(20);
    expect(screen.getAllByText("Model 1")[0]).toBeInTheDocument();
    size("50");
    expect(rows()).toHaveLength(23);
  });

  it("shows the capture's No data and no footer when there are no Creators", async () => {
    renderWithProviders(<Page />);
    await screen.findByText("No data");
    expect(screen.queryByText(/^Total:/)).toBeNull();
  });

  it("names a failed accounts read in the table body, titled as an extra, with no footer", async () => {
    relayGet.mockImplementation((path: string) =>
      path === "/admin/accounts" ? Promise.reject(new RelayError(500, null, "relay 500")) : Promise.resolve({}));
    renderWithProviders(<Page />);
    expect(await within(table()).findByText("relay 500")).toHaveAttribute("title", EXTRA_LABEL);
    expect(screen.queryByText(/^Total:/)).toBeNull();
  });
});

describe("/creators — extras between the table and the footer", () => {
  it("holds the founder key cards in one collapsed disclosure, drawn for a Master only", async () => {
    accounts = [{ id: "acct-a", nickname: "Alpha" }];
    me = { is_admin: true };
    const { unmount } = renderWithProviders(<Page />);
    await screen.findByText("Total: 1 creators");

    const summary = screen.getByText(EXTRAS_OVERFLOW_LABEL);
    const details = summary.closest("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(follows(table(), details)).toBe(true);
    expect(follows(details, screen.getByText("Total: 1 creators"))).toBe(true);
    for (const card of ["Other agencies' AI keys", "Server keys"]) {
      expect(details).toContainElement(screen.getAllByRole("heading", { name: card })[0]);
    }
    unmount();

    me = { is_admin: false };
    renderWithProviders(<Page />);
    await screen.findByText("Total: 1 creators");
    expect(screen.queryByText(EXTRAS_OVERFLOW_LABEL)).toBeNull();
    expect(screen.queryByRole("heading", { name: "Your AI keys" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Other agencies' AI keys" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Server keys" })).toBeNull();
  });

  it("shows the mirror freshness alarm above the footer, outside the disclosure and titled as an extra, to the founder only", async () => {
    accounts = [{ id: "acct-a", nickname: "Alpha" }];
    liveRev = { live_rev: "202612010900-abcdef0123" };
    me = { is_admin: true };
    const { unmount } = renderWithProviders(<Page />);
    const banner = (await screen.findByText("OF Manager mirror is behind OnlyFans")).closest(`[title="${EXTRA_LABEL}"]`)!;
    expect(banner).not.toBeNull();
    expect(follows(table(), banner)).toBe(true);
    expect(follows(banner, screen.getByText("Total: 1 creators"))).toBe(true);
    expect(screen.getByText(EXTRAS_OVERFLOW_LABEL).closest("details")).not.toContainElement(banner as HTMLElement);
    unmount();

    relayGet.mockClear();
    me = { is_admin: false };
    renderWithProviders(<Page />);
    await screen.findByText("Total: 1 creators");
    expect(relayGet).not.toHaveBeenCalledWith("/admin/rev/live");
    expect(screen.queryByText("OF Manager mirror is behind OnlyFans")).toBeNull();
  });

  it("never warns that a session is stale when OF ships a new build: a session outlives OF's frontend revs", async () => {
    accounts = [{ id: "acct-a", nickname: "Alpha", has_session: true }];
    liveRev = { live_rev: "202612010900-abcdef0123" };
    me = { is_admin: true };
    renderWithProviders(<Page />);
    await screen.findByText("OF Manager mirror is behind OnlyFans");
    expect(screen.queryByText(/Session stale|re-capture required/)).toBeNull();
  });
});

describe("/creators — the Employees column", () => {
  it("joins the names of the Employees whose Creator access holds the row, from the employee read the filter makes", async () => {
    accounts = [
      { id: "acct-1", nickname: "Alpha", has_session: true },
      { id: "acct-2", nickname: "Bravo", has_session: true },
    ];
    employees = () => Promise.resolve({
      employees: [
        { id: 1, display_name: "Emp One", color: null, is_active: true, account_ids: ["acct-2"], chatter_id: "c1" },
        { id: 2, display_name: "Emp Two", color: null, is_active: true, account_ids: null, chatter_id: "c2" },
        { id: 3, display_name: "Owner seat", color: null, is_active: true, account_ids: null, chatter_id: null },
      ],
    });
    renderWithProviders(<Page />);
    const col = () => within(table()).getAllByRole("columnheader").findIndex((h) => h.textContent === "Employees");
    const cell = (name: string) => within(rowOf(name)).getAllByRole("cell")[col()];
    await waitFor(() => expect(cell("Bravo")).toHaveTextContent("Emp One, Emp Two"));
    expect(cell("Alpha")).toHaveTextContent(/^Emp Two$/);
    expect(within(table()).getAllByRole("columnheader")[col()]).not.toHaveAttribute("title");
  });

  it("is Not wired when the employee read is refused", async () => {
    accounts = [{ id: "acct-1", nickname: "Alpha", has_session: true }];
    employees = () => Promise.reject(new RelayError(403, { detail: "owner only" }, "relay 403"));
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");
    const col = within(table()).getAllByRole("columnheader").findIndex((h) => h.textContent === "Employees");
    await waitFor(() =>
      expect(within(within(rowOf("Alpha")).getAllByRole("cell")[col]).getByText("—")).toHaveAttribute("title", "not wired"),
    );
  });
});

describe("/creators — the row's ⋮ menu", () => {
  const relayPost = relay.post as unknown as Mock;
  const relayPatch = relay.patch as unknown as Mock;
  const relayDelete = relay.delete as unknown as Mock;
  const openMenu = (name: string) => {
    fireEvent.click(within(rowOf(name)).getByRole("button", { name: `More actions for ${name}` }));
    return screen.getByRole("menu");
  };
  const items = (menu: HTMLElement) => within(menu).getAllByRole("menuitem");
  const fleet = () => {
    accounts = [
      { id: "acct-a", nickname: "Alpha", has_session: true },
      { id: "acct-b", nickname: "Bravo", has_session: true },
      { id: "acct-c", nickname: "Charlie", has_session: true },
    ];
    health = () => Promise.resolve({
      ok: true,
      accounts: [
        { account_id: "acct-a", ok: true },
        { account_id: "acct-b", ok: true },
        { account_id: "acct-c", ok: false, error: "auth_failed" },
      ],
    });
  };
  beforeEach(() => {
    relayPost.mockReset();
    relayPatch.mockReset();
    relayDelete.mockReset();
    relayPost.mockResolvedValue({});
    relayPatch.mockResolvedValue({});
    relayDelete.mockResolvedValue({ ok: true });
  });

  it("holds the capture's items in its order, then our extras, each titled as an extra", async () => {
    fleet();
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Bravo")).toHaveTextContent("Connected"));

    expect(within(rowOf("Bravo")).getByRole("button", { name: "Edit" })).toBeEnabled();

    const menu = openMenu("Bravo");
    expect(items(menu).map((i) => i.textContent)).toEqual([
      "Link another account", "Deactivate", "Delete", "Rename", "Make default",
    ]);
    expect(within(menu).getByRole("menuitem", { name: "Deactivate" })).toBeEnabled();
    expect(within(menu).getByRole("menuitem", { name: "Link another account" })).toBeEnabled();
    expect(within(menu).getByRole("menuitem", { name: "Delete" })).toBeEnabled();
    for (const label of ["Link another account", "Deactivate", "Delete"]) {
      expect(within(menu).getByRole("menuitem", { name: label }).querySelector("svg")).not.toBeNull();
    }
    const extras = within(menu).getByRole("group", { name: EXTRA_LABEL });
    for (const label of ["Rename", "Make default"]) {
      const item = within(extras).getByRole("menuitem", { name: label });
      expect(item).toBeEnabled();
      expect(item).toHaveAttribute("title", EXTRA_LABEL);
    }
  });

  it("Link another account opens on the other platform's sign-in, the taken one not offered", async () => {
    fleet();
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Bravo")).toHaveTextContent("Connected"));
    fireEvent.click(within(openMenu("Bravo")).getByRole("menuitem", { name: "Link another account" }));
    const d = screen.getByRole("dialog", { name: "Link creator account" });
    expect(within(d).getAllByRole("region").map((r) => r.getAttribute("aria-label"))).toEqual(["Fansly paste session"]);
    expect(within(d).queryByRole("button", { name: /Link an OnlyFans account/ })).toBeNull();
  });

  it("Edit account details saves the nickname, Tag, notes and Creator access, and Change proxy rebinds the proxy", async () => {
    fleet();
    employees = () => Promise.resolve({
      employees: [{ id: 1, display_name: "Emp One", color: null, is_active: true, account_ids: ["acct-b", "acct-c"], chatter_id: "c1" }],
    });
    proxies = () => Promise.resolve({ proxies: [
      { label: "px-1", scheme: "http", host: "10.0.0.1", port: 8000, assigned_account_ids: ["acct-b"] },
      { label: "px-2", scheme: "http", host: "10.0.0.2", port: 8000, assigned_account_ids: [] },
    ], pool: { size: 0, account_ids: [] }, accounts: [] });
    relayPost.mockImplementation((path: string) => Promise.resolve(path.endsWith("/test") ? { ok: true } : {}));
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Bravo")).toHaveTextContent("Connected"));
    await waitFor(() => expect(extrasOf("Bravo")).toContain("px-1"));
    fireEvent.click(within(rowOf("Bravo")).getByRole("button", { name: "Edit" }));
    const d = screen.getByRole("dialog", { name: "Edit account details" });
    expect(within(d).getByText("Linked account")).toBeInTheDocument();
    expect(within(d).getByRole("button", { name: "Unlink" })).toHaveAttribute("title", "not wired");
    expect(within(d).getByText("px-1 http 10.0.0.1:8000")).toBeInTheDocument();
    await waitFor(() => expect(within(d).getByRole("button", { name: "Save" })).toBeEnabled());
    fireEvent.change(within(d).getByLabelText("Creator name"), { target: { value: "Bravo Creator" } });
    fireEvent.change(within(d).getByLabelText("Nickname"), { target: { value: "Bravo B" } });
    fireEvent.change(within(d).getByLabelText("Tag (Optional)"), { target: { value: "VIP" } });
    fireEvent.click(within(d).getByRole("button", { name: "Assigned employees" }));
    fireEvent.click(within(d).getByRole("option", { name: "Emp One" }));
    fireEvent.click(within(d).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(relayPatch).toHaveBeenCalledWith("/admin/accounts/acct-b", { nickname: "Bravo B" });
    expect(relayPut).toHaveBeenCalledWith("/admin/employees/1/access", { account_ids: ["acct-c"] });
    expect((settings as { creators: { profiles: Record<string, unknown> } }).creators.profiles["acct-b"])
      .toEqual(expect.objectContaining({ name: "Bravo Creator", tag: "VIP" }));
    expect(screen.getByText("Update Success")).toBeInTheDocument();

    fireEvent.click(within(rowOf("Bravo Creator")).getByRole("button", { name: "Edit" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Edit account details" })).getByRole("button", { name: "Change" }));
    const change = screen.getByRole("dialog", { name: "Change proxy" });
    fireEvent.click(within(change).getByRole("button", { name: "px-2 http 10.0.0.2:8000" }));
    await waitFor(() => expect(within(change).getByRole("button", { name: "Save" })).toBeEnabled());
    fireEvent.click(within(change).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByText("Switch Proxy Success")).toBeInTheDocument());
    expect(relayPost).toHaveBeenCalledWith("/admin/proxies/px-1/unbind", { account_id: "acct-b" });
    expect(relayPost).toHaveBeenCalledWith("/admin/proxies/assign", { label: "px-2", account_id: "acct-b" });
    expect(relayPost).toHaveBeenCalledWith("/admin/reload-session?account_id=acct-b");
  });

  it("Change proxy stays disabled until the proxies read answers", async () => {
    fleet();
    let answer: (v: unknown) => void = () => {};
    proxies = () => new Promise((r) => { answer = r; });
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Bravo")).toHaveTextContent("Connected"));
    fireEvent.click(within(rowOf("Bravo")).getByRole("button", { name: "Edit" }));
    const d = screen.getByRole("dialog", { name: "Edit account details" });
    expect(within(d).getByRole("button", { name: "Change" })).toBeDisabled();
    answer({ proxies: [], pool: { size: 1, account_ids: ["acct-b"] }, accounts: [] });
    await waitFor(() => expect(within(d).getByRole("button", { name: "Change" })).toBeEnabled());
    expect(within(d).getByText("Inflowwww proxy")).toBeInTheDocument();
  });

  it("an account on the pool reads Inflowwww proxy; Change proxy moves it to No proxy, and a custom one onto the pool", async () => {
    fleet();
    proxies = () => Promise.resolve({
      proxies: [{ label: "px-1", scheme: "http", host: "10.0.0.1", port: 8000, assigned_account_ids: ["acct-a"] }],
      pool: { size: 2, account_ids: ["acct-b"] }, accounts: [],
    });
    renderWithProviders(<Page />);
    await waitFor(() => expect(extrasOf("Bravo")).toContain("Inflowwww proxy"));
    expect(extrasOf("Alpha")).toContain("Custom proxy · px-1");

    fireEvent.click(within(rowOf("Bravo")).getByRole("button", { name: "Edit" }));
    let d = screen.getByRole("dialog", { name: "Edit account details" });
    expect(within(d).getByText("Inflowwww proxy")).toBeInTheDocument();
    fireEvent.click(within(d).getByRole("button", { name: "Change" }));
    let change = screen.getByRole("dialog", { name: "Change proxy" });
    expect(within(change).getByRole("radio", { name: /^Inflowwww proxy/ })).toBeChecked();
    expect(within(change).queryByRole("list", { name: "Proxies" })).toBeNull();
    fireEvent.click(within(change).getByRole("radio", { name: /^No proxy/ }));
    fireEvent.click(within(change).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByText("Switch Proxy Success")).toBeInTheDocument());
    expect(relayPost).toHaveBeenCalledWith("/admin/proxy-pool/unbind", { account_id: "acct-b" });
    expect(relayPost).toHaveBeenCalledWith("/admin/reload-session?account_id=acct-b");
    expect(relayPost).not.toHaveBeenCalledWith("/admin/proxy-pool/assign", expect.anything());
    fireEvent.click(within(screen.getByRole("dialog", { name: "Edit account details" })).getByRole("button", { name: "Cancel" }));

    relayPost.mockClear();
    fireEvent.click(within(rowOf("Alpha")).getByRole("button", { name: "Edit" }));
    d = screen.getByRole("dialog", { name: "Edit account details" });
    expect(within(d).getByText("px-1 http 10.0.0.1:8000")).toBeInTheDocument();
    fireEvent.click(within(d).getByRole("button", { name: "Change" }));
    change = screen.getByRole("dialog", { name: "Change proxy" });
    fireEvent.click(within(change).getByRole("radio", { name: /^Inflowwww proxy/ }));
    fireEvent.click(within(change).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/proxy-pool/assign", { account_id: "acct-a" }));
    expect(relayPost).toHaveBeenCalledWith("/admin/reload-session?account_id=acct-a");
    expect(relayPost).not.toHaveBeenCalledWith("/admin/proxies/assign", expect.anything());
  });

  it("Delete asks in the capture's two-step modal, then posts the delete for that Creator only; Close and Escape post nothing", async () => {
    fleet();
    renderWithProviders(<Page />);
    await screen.findAllByText("Bravo");
    const dialog = () => screen.getByRole("dialog", { name: "Delete Bravo" });

    fireEvent.click(within(openMenu("Bravo")).getByRole("menuitem", { name: "Delete" }));
    expect(within(dialog()).getByText("Step 1 of 2")).toBeInTheDocument();
    expect(within(dialog()).getByRole("button", { name: "Back" })).toBeDisabled();
    expect(relayDelete).not.toHaveBeenCalled();
    fireEvent.click(within(dialog()).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(within(openMenu("Bravo")).getByRole("menuitem", { name: "Delete" }));
    fireEvent.keyDown(dialog(), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(relayDelete).not.toHaveBeenCalled();

    fireEvent.click(within(openMenu("Bravo")).getByRole("menuitem", { name: "Delete" }));
    expect(dialog()).toHaveTextContent("All platform accounts and related data under Bravo will be permanently deleted from Inflowwww. This action cannot be undone.");
    fireEvent.click(within(dialog()).getByRole("button", { name: "Delete creator" }));
    expect(within(dialog()).getByText("Step 2 of 2")).toBeInTheDocument();
    expect(within(dialog()).getByRole("group", { name: /Why are you deleting the creator's account\?/ })).toBeInTheDocument();
    fireEvent.click(within(dialog()).getByLabelText("Others"));
    expect(within(dialog()).getByLabelText("Reason for deleting creator")).toHaveAttribute("maxLength", "120");
    expect(relayDelete).not.toHaveBeenCalled();
    fireEvent.click(within(dialog()).getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(relayDelete).toHaveBeenCalledWith("/admin/accounts/acct-b"));
    expect(relayDelete).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText("Bravo deleted")).toBeInTheDocument();
  });

  it("Rename edits the Creator name in place, Make default posts the default", async () => {
    fleet();
    renderWithProviders(<Page />);
    await screen.findAllByText("Bravo");

    fireEvent.click(within(openMenu("Bravo")).getByRole("menuitem", { name: "Rename" }));
    const box = within(rowOf("Bravo")).getByRole("textbox");
    fireEvent.change(box, { target: { value: "Bravo Two" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(relayPatch).toHaveBeenCalledWith("/admin/accounts/acct-b", { nickname: "Bravo Two" }));

    fireEvent.click(within(openMenu("Bravo")).getByRole("menuitem", { name: "Make default" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/accounts/active", { account_id: "acct-b" }));

    expect(items(openMenu("Alpha")).map((i) => i.textContent)).not.toContain("Make default");
    expect(items(screen.getByRole("menu")).map((i) => i.textContent)).not.toContain("Refresh session");
  });

  it("each recovery action opens the Add creator modal at the section that performs it, or is Not wired", async () => {
    fleet();
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Charlie")).toHaveTextContent("Disconnected"));
    const dialog = () => screen.getByRole("dialog", { name: "Link creator account" });
    const close = () => fireEvent.click(within(dialog()).getByRole("button", { name: "Close" }));

    expect(within(rowOf("Bravo")).queryByRole("button", { name: "Link creator account" })).toBeNull();
    expect(items(openMenu("Bravo")).map((i) => i.textContent)).not.toContain("Log in to account via OnlyFans");
    fireEvent.mouseDown(document.body);

    fireEvent.click(within(rowOf("Charlie")).getByRole("button", { name: "Link creator account" }));
    expect(within(dialog()).getByRole("region", { name: "Browserbase login" })).toHaveFocus();
    expect(within(dialog()).queryByRole("button", { name: /Link a Fansly account/ })).toBeNull();
    close();

    const menu = openMenu("Charlie");
    expect(items(menu).map((i) => i.textContent)).toEqual([
      "Edit", "Link another account", "Deactivate", "Delete",
      "Log in to account via OnlyFans", "Log in to account via Login+",
      "Rename", "Make default",
    ]);
    expect(within(menu).getByRole("menuitem", { name: "Edit" })).toBeEnabled();
    const loginPlus = within(menu).getByRole("menuitem", { name: "Log in to account via Login+" });
    expect(loginPlus).toBeDisabled();
    expect(loginPlus).toHaveAttribute("title", "not wired");
    fireEvent.mouseDown(document.body);

    fireEvent.click(within(openMenu("Charlie")).getByRole("menuitem", { name: "Log in to account via OnlyFans" }));
    expect(within(dialog()).getByRole("region", { name: "Browserbase login" })).toHaveFocus();
    close();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens straight at Browserbase login from a ?relink=browserbase link (a 2FA notification), once", async () => {
    fleet();
    window.history.replaceState(null, "", "/creators?relink=browserbase");
    try {
      renderWithProviders(<Page />);
      const d = await screen.findByRole("dialog", { name: "Link creator account" });
      await waitFor(() => expect(within(d).getByRole("region", { name: "Browserbase login" })).toHaveFocus());
      expect(window.location.search).toBe("");
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });

  it("ignores any other ?relink= value, a sign-in section included (only a 2FA notification links here)", async () => {
    fleet();
    window.history.replaceState(null, "", "/creators?relink=paste");
    try {
      renderWithProviders(<Page />);
      await waitFor(() => expect(connCell("Charlie")).toHaveTextContent("Disconnected"));
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(window.location.search).toBe("");
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });

  it("a re-link's linked step shows the proxy the relay has the account on, not No proxy", async () => {
    fleet();
    proxies = () => Promise.resolve({
      proxies: [{ label: "px-1", scheme: "http", host: "10.0.0.1", port: 8000, assigned_account_ids: ["acct-b"] }],
      pool: { size: 2, account_ids: ["acct-c"] }, accounts: [],
    });
    relayPost.mockImplementation((path: string) => Promise.resolve(path === "/admin/session/bootstrap"
      ? { account_id: "acct-c", user_id: 7, session_file: "s.json", x_of_rev: "rev-1" } : {}));
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Charlie")).toHaveTextContent("Disconnected"));
    fireEvent.click(within(openMenu("Charlie")).getByRole("menuitem", { name: "Log in to account via OnlyFans" }));
    const d = screen.getByRole("dialog", { name: "Link creator account" });
    const bb = within(d).getByRole("region", { name: "Browserbase login" });
    expect(within(bb).getByText(/^Keeps its current proxy\./)).toBeInTheDocument();
    fireEvent.click(within(d).getByRole("radio", { name: /^Extension/ }));
    const paste = within(d).getByRole("region", { name: "Extension" });
    expect(within(paste).queryByText(/assigned after linking/)).toBeNull();
    fireEvent.change(within(paste).getByLabelText("Copied cURL"), { target: { value: "curl 'https://onlyfans.com/api2/v2/x' -b 'sess=1' -A 'UA'" } });
    fireEvent.click(within(d).getByRole("button", { name: "Link account" }));
    await within(d).findByText("Creator account is linked to Inflowwww");
    expect(await within(d).findByText("Inflowwww proxy")).toBeInTheDocument();
    expect(relayPost).not.toHaveBeenCalledWith("/admin/proxy-pool/assign", expect.anything());
    expect(within(d).queryByText("Account details")).toBeNull();
    fireEvent.click(within(d).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a re-login through Browserbase sends No proxy, so the relay keeps the account's binding", async () => {
    fleet();
    proxies = () => Promise.resolve({ proxies: [], pool: { size: 2, account_ids: ["acct-c"] }, accounts: [] });
    relayPost.mockImplementation(() => Promise.resolve({}));
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Charlie")).toHaveTextContent("Disconnected"));
    fireEvent.click(within(openMenu("Charlie")).getByRole("menuitem", { name: "Log in to account via OnlyFans" }));
    const d = screen.getByRole("dialog", { name: "Link creator account" });
    const bb = within(d).getByRole("region", { name: "Browserbase login" });
    fireEvent.change(within(bb).getByLabelText("OnlyFans email"), { target: { value: "a@b.c" } });
    fireEvent.change(within(bb).getByLabelText("OnlyFans password"), { target: { value: "pw" } });
    fireEvent.click(within(d).getByRole("button", { name: "Start browser login" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/login/remote/start", expect.objectContaining({ proxy: "none" })));
  });
});

describe("/creators — a chatter session", () => {
  it("renders the table with the proxy cells Not wired and no error banner when the proxies read answers 403", async () => {
    me = null;
    accounts = [{ id: "acct-a", nickname: "Alpha", has_session: true }];
    proxies = () => Promise.reject(new RelayError(403, { detail: "owner only" }, "relay 403"));
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");
    await waitFor(() => expect(extrasOf("Alpha")).toContain("Custom proxy: not wired"));
    expect(screen.queryByText(/relay 403|owner only/)).toBeNull();
  });
  it("renders the table with the employee filter Not wired and no error banner when the employees and proxies reads answer 403", async () => {
    me = null;
    accounts = [{ id: "acct-a", nickname: "Alpha", has_session: true }];
    proxies = () => Promise.reject(new RelayError(403, { detail: "owner only" }, "relay 403"));
    employees = () => Promise.reject(new RelayError(403, { detail: "owner only" }, "relay 403"));
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");
    const emp = screen.getByRole("combobox", { name: "Employee" });
    await waitFor(() => expect(emp).toBeDisabled());
    expect(emp).toHaveAttribute("title", "not wired");
    expect(screen.queryByText(/relay 403|owner only/)).toBeNull();
    expect(rows()).toHaveLength(1);
  });

  it("leaves the employee filter Not wired for an owner whose employees read is refused", async () => {
    accounts = [{ id: "acct-a", nickname: "Alpha", has_session: true }];
    employees = () => Promise.reject(new RelayError(403, { detail: "owner only" }, "relay 403"));
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");
    const emp = screen.getByRole("combobox", { name: "Employee" });
    await waitFor(() => expect(emp).toBeDisabled());
    expect(emp).toHaveAttribute("title", "not wired");
    expect(screen.queryByText(/relay 403|owner only/)).toBeNull();
  });
});
