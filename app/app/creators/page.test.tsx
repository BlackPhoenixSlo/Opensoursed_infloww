/**
 * The `/creators` route module renders Manage creators as the Layout capture
 * draws it (docs/infloww-layouts/creators-manage.md; docs/spec/
 * infloww-parity-round-2/phase-04-creators-pages.md, Testing Decisions, the
 * Manage creators page seam; ticket 13). The Relay client is mocked as in
 * AccountsTable.test.tsx. Fixture names and ids are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { renderWithProviders } from "@/test-utils";
import { EXTRA_LABEL, EXTRAS_OVERFLOW_LABEL } from "@/lib/openinflowwwwExtras";
import { GENDERS } from "@/lib/creatorProfiles";

vi.mock("@/lib/relay", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/relay")>()),
  relay: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
let me: { is_admin?: boolean } | null;
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: me, loading: false }) }));

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
let drift: unknown;
/** The agency's `account` Settings blob, whose `creators` key holds the Creator profiles (useCreatorProfiles). */
let settings: Record<string, unknown> | null;
let fetchMock: Mock;

beforeEach(() => {
  me = { is_admin: false };
  accounts = [];
  health = () => Promise.resolve({ ok: true, accounts: [] });
  proxies = () => Promise.resolve({ proxies: [], pool: { size: 0, account_ids: [] }, accounts: [] });
  employees = () => Promise.resolve({ employees: [] });
  drift = { any_drift: false, live_rev: "rev-1", accounts: [] };
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
    if (path === "/admin/rev/drift") return Promise.resolve(drift);
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
/** The capture's connectivity cell: the column headed "Connectivity status". */
const connCell = (name: string) => {
  const i = within(table()).getAllByRole("columnheader").findIndex((h) => h.textContent === "Connectivity status");
  return within(rowOf(name)).getAllByRole("cell")[i];
};
const follows = (a: Node, b: Node) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
/** The Creator cell's title: our extras the capture has no column for (the id, the bound proxy, last used). */
const extrasOf = (name: string) => within(rowOf(name)).getAllByRole("cell")[1].querySelector("[title]")?.getAttribute("title") ?? "";

describe("/creators — the creator table leads", () => {
  it("renders the table before any capture form, with the capture's column headers in order", async () => {
    accounts = [{ id: "acct-a", nickname: "Alpha", has_session: true }];
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Manage creators"); // creators-manage#3
    const headers = within(table()).getAllByRole("columnheader");
    // 01-home.png's columns, in its order, and no column of ours (page-parity 02).
    expect(headers.map((h) => h.textContent)).toEqual([
      "", //                    creators-manage#29 (the untitled expand column)
      "Creator", //             creators-manage#30
      "Nickname", //            creators-manage#32
      "Tag", //                 creators-manage#34
      "Account", //             creators-manage#36
      "Creator ID", //          creators-manage#37
      "Employees", //           creators-manage#38
      "Connectivity status", // creators-manage#39
      "Action", //              creators-manage#43
    ]);
    // HB's head: #171717 (`bg-panel`), white text; the fixed Action column the same, with its left rule.
    for (const h of headers) expect(h).toHaveClass("bg-panel", "text-white");
    expect(headers[headers.length - 1]).toHaveClass("border-l", "border-[#2c2c2c]");
    // The HB page body and the orange Add creator (black text on the action fill).
    expect(screen.getByRole("button", { name: "Add creator" })).toHaveClass("bg-cta", "text-black");

    // The capture forms are no longer on the page: they live in the Add creator modal (ticket 14).
    for (const form of ["Paste cURL", /^Connect Fansly/]) {
      expect(screen.queryByRole("heading", { name: form })).toBeNull();
    }
    // The Tag settings gear (creators-manage#35) opens the Tag manager once the account details are read (TagSettings).
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
    expect(within(row).getByText("Fansly")).toBeInTheDocument(); // creators-manage#20
    // The account id and the bound proxy are the Creator cell's title, labelled ours (no extra column).
    expect(extrasOf("Foxtrot")).toContain("acct-f");
    expect(extrasOf("Foxtrot").startsWith(EXTRA_LABEL)).toBe(true);
    await waitFor(() => expect(extrasOf("Foxtrot")).toContain("Custom proxy · px-1"));
    // No new Relay route: the page reads the spec's four (Contracts), plus the extras' own reads.
    const paths = new Set(relayGet.mock.calls.map(([p]) => String(p)));
    for (const p of paths) {
      expect([
        "/admin/accounts", "/health?all_accounts=1", "/admin/proxies", "/admin/employees?include_disabled=false",
        "/admin/rev/drift", "/admin/my-llm-keys", "/admin/settings/account",
      ]).toContain(p);
    }
  });


  it("fills Creator ID with the OnlyFans @username from the /users/me read the avatar makes", async () => {
    accounts = [{ id: "acct-o", nickname: "Oscar", platform: "onlyfans", has_session: true }];
    const base = relayGet.getMockImplementation()!;
    relayGet.mockImplementation((path: string, opts?: unknown) =>
      path === "/api/of/v2/users/me" ? Promise.resolve({ username: "oscar_of", avatar: null }) : base(path, opts));
    renderWithProviders(<Page />);
    await screen.findAllByText("Oscar");
    const i = within(table()).getAllByRole("columnheader").findIndex((h) => h.textContent === "Creator ID");
    await waitFor(() => expect(within(rowOf("Oscar")).getAllByRole("cell")[i]).toHaveTextContent("@oscar_of"));
    // The Account cell: the platform's name after its mark.
    expect(within(rowOf("Oscar")).getByText("OnlyFans")).toBeInTheDocument();
    // The default Creator's badge follows its nickname.
    expect(within(rowOf("Oscar")).getByText("default")).toBeInTheDocument();
  });
});

describe("/creators — the filter bar narrows the table", () => {
  const names = () => rows().map((r) => within(r).getAllByRole("cell")[1].textContent);
  const filter = (name: string) => screen.getByRole("combobox", { name });
  const search = () => screen.getByRole("textbox", { name: "Creator name" });
  /** The Employee filter searches (creators-manage#24, `showSearch`): a text box over a list of its names. */
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
        { account_id: "acct-3", ok: true }, // a dead session whose probe is live
        { account_id: "acct-4", ok: false, error: "no_session" },
      ],
    });
    employees = () => Promise.resolve({
      employees: [
        { id: 1, display_name: "Emp One", color: null, is_active: true, account_ids: ["acct-2"], chatter_id: "c1" },
        { id: 2, display_name: "Emp Two", color: null, is_active: true, account_ids: null, chatter_id: "c2" }, // every Creator
      ],
    });
  };
  const ALL = ["Alpha", "Bravo", "Charlie", "Delta"];

  it("draws the capture's six filters in its order, with its options, and no Reset", async () => {
    roster();
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");
    const bar = screen.getByRole("search", { name: "Filter creators" });
    // The capture's order (creators-manage#14, #18 to #25). Its labels are keys with no English on disk, so the
    // words are the Clone's (its Clone fixes for #18 to #25), as the capture's Notes allow.
    const controls = [within(bar).getByRole("textbox"), ...within(bar).getAllByRole("combobox")];
    expect(follows(controls[0], controls[1])).toBe(true);
    expect(controls.map((c) => c.getAttribute("aria-label"))).toEqual([
      "Creator name", //        creators-manage#18 (growth0094)
      "Platform", //            creators-manage#19 (settings0125)
      "Tag", //                 creators-manage#21 (creators0275)
      "Connectivity status", // creators-manage#22 (creators0064)
      "Employee", //            creators-manage#24 (employee0055)
      "Account status", //      creators-manage#25 (creators0022)
    ]);
    expect(search()).toHaveAttribute("maxLength", "50"); // creators-manage#18
    const opts = (name: string) => within(filter(name)).getAllByRole("option").map((o) => o.textContent);
    const searchable = (name: string) => [...(listOf(filter(name))?.querySelectorAll("option") ?? [])].map((o) => o.value);
    expect(opts("Platform")).toEqual(["Platform", "OnlyFans", "Fansly"]); // creators-manage#20
    expect(opts("Connectivity status")).toEqual([
      "Connectivity status", "Connected", "Disconnected", "Not connected", "Pending connection", "2FA required",
    ]); // creators-manage#23
    await waitFor(() => expect(searchable("Employee")).toEqual(["Emp One", "Emp Two"]));
    expect(filter("Employee")).toHaveAttribute("placeholder", "Employee");
    expect(opts("Account status")).toEqual(["Account status", "Activated", "Deactivated"]); // creators-manage#26
    // The bundle has no Reset (the capture's Notes, #14), and neither do we (page-parity 02): each filter clears itself.
    expect(within(bar).queryByRole("button")).toBeNull();
    // HB's filled filter: #161616, no border.
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
    pick("Tag", "Tag"); // the select's own first option clears it
    expect(names()).toEqual(["Alpha Creator", "Bravo", "Charlie", "Delta"]);
  });

  it("joins a row's Employees with \", \" and keeps the full list on hover past the two-line clamp", async () => {
    roster();
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");
    const i = within(table()).getAllByRole("columnheader").findIndex((h) => h.textContent === "Employees");
    const cell = (name: string) => within(rowOf(name)).getAllByRole("cell")[i].firstElementChild!;
    // creators-manage#38: names joined ", ", two lines (`-webkit-line-clamp:2`), the full list in its popover.
    await waitFor(() => expect(cell("Bravo")).toHaveTextContent("Emp One, Emp Two"));
    expect(cell("Bravo")).toHaveAttribute("title", "Emp One, Emp Two");
    expect(cell("Alpha")).toHaveAttribute("title", "Emp Two");
  });

  it("narrows by search, platform, connectivity and employee, and each filter clears on its own", async () => {
    roster();
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Alpha")).toHaveTextContent("Connected"));
    expect(names()).toEqual(ALL);

    // Search applies on Enter, never on typing alone (creators-manage#18: `onPressEnter`), on the Creator name or its
    // id.
    fireEvent.change(search(), { target: { value: "rav" } });
    expect(names()).toEqual(ALL);
    fireEvent.keyDown(search(), { key: "Enter" });
    expect(names()).toEqual(["Bravo"]);
    fireEvent.change(search(), { target: { value: "ACCT-4" } });
    expect(names()).toEqual(["Bravo"]);
    fireEvent.keyDown(search(), { key: "Enter" });
    expect(names()).toEqual(["Delta"]);
    // Emptied, then Enter, the name filter clears.
    fireEvent.change(search(), { target: { value: "" } });
    fireEvent.keyDown(search(), { key: "Enter" });
    expect(names()).toEqual(ALL);

    pick("Platform", "Fansly");
    expect(names()).toEqual(["Bravo"]);
    pick("Platform", "OnlyFans");
    expect(names()).toEqual(["Alpha", "Charlie", "Delta"]);
    pick("Platform", "Platform");
    expect(names()).toEqual(ALL);

    // The row's own status: the dead session with a live probe is Disconnected.
    pick("Connectivity status", "Disconnected");
    expect(names()).toEqual(["Bravo", "Charlie"]);
    pick("Connectivity status", "Connected");
    expect(names()).toEqual(["Alpha"]);
    pick("Connectivity status", "Not connected");
    expect(names()).toEqual(["Delta"]);
    // A login-job state: no stored Creator is in it.
    pick("Connectivity status", "2FA required");
    expect(screen.getByText("No data")).toBeInTheDocument();
    expect(screen.queryByText(/^Total:/)).toBeNull();
    pick("Connectivity status", "Connectivity status");

    // Employees' Creator access: a list grants those Creators, null grants every one. The box searches: a part of a
    // name only narrows the list it offers, and the table waits for a whole name (creators-manage#24).
    await waitFor(() => expect(listOf(filter("Employee"))?.querySelectorAll("option")).toHaveLength(2));
    fireEvent.change(filter("Employee"), { target: { value: "one" } });
    expect(names()).toEqual(ALL);
    pick("Employee", "Emp One");
    expect(names()).toEqual(["Bravo"]);
    expect(screen.getByText("Total: 1 creators")).toBeInTheDocument();
    pick("Employee", "Emp Two");
    expect(names()).toEqual(ALL);
    pick("Employee", "Emp One");
    fireEvent.change(filter("Employee"), { target: { value: "" } }); // cleared, as antd's allowClear
    expect(names()).toEqual(ALL);

    // Filters combine.
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

describe("/creators — Add creator, Infloww's steps", () => {
  const relayPost = relay.post as unknown as Mock;
  const relayPatch = relay.patch as unknown as Mock;
  const dialog = () => screen.getByRole("dialog");
  const open = async () => {
    fireEvent.click(await screen.findByRole("button", { name: "Add creator" }));
    return screen.getByRole("dialog", { name: "Add creator" });
  };
  const btn = (name: string | RegExp) => within(dialog()).getByRole("button", { name });
  /** Step 1, filled in: Creator name and Gender. */
  const details = (name = "Nova") => {
    fireEvent.change(within(dialog()).getByLabelText("Creator name"), { target: { value: name } });
    fireEvent.change(within(dialog()).getByLabelText("Gender"), { target: { value: "Female" } });
  };
  /** Steps 1 to 3 with an OnlyFans account and the automatic proxy: the sign-in step. */
  const toLogin = async () => {
    await open();
    details();
    await waitFor(() => expect(btn("Done")).toBeEnabled()); // the profile store answered
    fireEvent.click(btn("Next: Link creator account"));
    await within(dialog()).findByText("Which platform’s account would you like to link?");
    fireEvent.click(btn("Next"));
    await within(dialog()).findByText("Proxy selection");
    fireEvent.click(btn("Connect OnlyFans"));
    return within(dialog()).findByText("Link OnlyFans account");
  };
  beforeEach(() => {
    relayPost.mockReset();
    relayPatch.mockReset();
    relayPost.mockResolvedValue({});
    relayPatch.mockResolvedValue({});
  });

  it("sits in the page header and opens at Creator details: Display image, Creator name, Gender, Done and Next", async () => {
    accounts = [{ id: "acct-a", nickname: "Alpha", has_session: true }];
    renderWithProviders(<Page />);
    await screen.findAllByText("Alpha");

    // creators-manage#9: the header's primary button, beside the title.
    const add = within(screen.getByRole("banner")).getByRole("button", { name: "Add creator" });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(add);
    const d = screen.getByRole("dialog", { name: "Add creator" });
    expect(within(d).getByText("Creator details")).toBeInTheDocument();
    expect(within(d).getByRole("button", { name: "Display image" })).toBeInTheDocument();
    expect(within(d).getByLabelText("Creator name")).toHaveAttribute("maxLength", "50");
    expect([...within(d).getByLabelText("Gender").querySelectorAll("option")].map((o) => o.textContent))
      .toEqual(["", ...GENDERS]); // Infloww's `genderOptions`, in its order
    // The old placeholder chips are gone.
    expect(within(d).queryByRole("region", { name: "Add creator steps" })).toBeNull();

    // Both buttons wait for a valid form (employee0118, employee0121).
    expect(within(d).getByRole("button", { name: "Done" })).toBeDisabled();
    expect(within(d).getByRole("button", { name: "Next: Link creator account" })).toBeDisabled();
    fireEvent.change(within(d).getByLabelText("Creator name"), { target: { value: "No-dash!" } });
    fireEvent.blur(within(d).getByLabelText("Creator name"));
    expect(within(d).getByText("Please input [0-9] or [a-z] or [A-Z]")).toBeInTheDocument();
    details("Nova Star");
    await waitFor(() => expect(within(d).getByRole("button", { name: "Done" })).toBeEnabled());
    expect(within(d).getByRole("button", { name: "Next: Link creator account" })).toBeEnabled();

    // Close (×) shuts it; the backdrop does not (`maskClosable:false`, creators-manage#54).
    fireEvent.click(d.parentElement!);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(within(d).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("Done saves the Creator to the profile store and lists it as Pending connection, with Link, Edit and Delete", async () => {
    renderWithProviders(<Page />);
    await screen.findByText("No data");
    await open();
    details("Nova");
    await waitFor(() => expect(btn("Done")).toBeEnabled());
    fireEvent.click(btn("Done"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(relayPut).toHaveBeenCalledWith("/admin/settings/account", expect.objectContaining({
      language: "en", // every other key rides along
      creators: { drafts: [expect.objectContaining({ name: "Nova", gender: "Female" })] },
    }));
    expect(screen.getByText("New creator added")).toBeInTheDocument();
    await waitFor(() => expect(connCell("Nova")).toHaveTextContent("Pending connection"));

    // Its Link creator account opens the flow at the platform step, under the later steps' title.
    fireEvent.click(within(rowOf("Nova")).getByRole("button", { name: "Link creator account" }));
    expect(screen.getByRole("dialog", { name: "Link creator account" })).toHaveTextContent("Which platform’s account would you like to link?");
    fireEvent.click(btn("Close"));

    // Edit creator details, then Delete with Infloww's message and survey.
    fireEvent.click(within(rowOf("Nova")).getByRole("button", { name: "More actions for Nova" }));
    expect(within(screen.getByRole("menu")).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Edit", "Delete"]);
    fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "Edit" }));
    const edit = screen.getByRole("dialog", { name: "Edit creator details" });
    fireEvent.change(within(edit).getByLabelText("Creator name"), { target: { value: "Nova Two" } });
    fireEvent.click(within(edit).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(rowOf("Nova Two")).toBeDefined());

    fireEvent.click(within(rowOf("Nova Two")).getByRole("button", { name: "More actions for Nova Two" }));
    fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "Delete" }));
    const del = screen.getByRole("dialog", { name: "Delete Nova Two" });
    expect(del).toHaveTextContent("All platform accounts and related data under Nova Two will be permanently deleted from Inflowwww.");
    fireEvent.click(within(del).getByRole("button", { name: "Delete creator" }));
    fireEvent.click(within(del).getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(screen.getByText("No data")).toBeInTheDocument());
    expect((settings as { creators: { drafts: unknown[] } }).creators.drafts).toEqual([]);
    expect(screen.getByText("Nova Two deleted")).toBeInTheDocument();
  });

  it("goes platform, then proxy, then the sign-in: Paste cURL and Browserbase login, extras, preset with the name", async () => {
    renderWithProviders(<Page />);
    await toLogin();
    // Step 1's Next saved the Creator first (addCreators).
    expect(relayPut).toHaveBeenCalledWith("/admin/settings/account", expect.objectContaining({
      creators: { drafts: [expect.objectContaining({ name: "Nova" })] },
    }));
    const d = dialog();
    expect(d).toHaveAccessibleName("Link creator account");
    // The OnlyFans sign-in keeps the proxy step's dots (#68).
    expect(within(d).getByText("Step 1 of 3")).toBeInTheDocument();
    const sections = within(d).getAllByRole("region");
    expect(sections.map((s) => s.getAttribute("aria-label"))).toEqual(["Paste cURL", "Browserbase login"]);
    for (const s of sections) {
      expect(s).toHaveAttribute("title", EXTRA_LABEL);
      expect(within(s).getByText(EXTRA_LABEL)).toBeInTheDocument();
    }
    expect(within(sections[0]).getByRole("heading", { name: "Paste cURL" })).toBeInTheDocument();
    expect(within(sections[0]).getByDisplayValue("Nova")).toBeInTheDocument();
    // The only password sign-in is the Browserbase card (a remote browser through a required proxy).
    expect(within(d).queryByRole("heading", { name: "Log in to OnlyFans" })).toBeNull();
    expect(within(sections[0]).queryByText(/Password/)).toBeNull();
    expect(within(sections[1]).getByRole("heading", { name: "Try Browserbase login" })).toBeInTheDocument();
    expect(within(sections[1]).getByRole("button", { name: "Try Browserbase login" })).toBeDisabled();
    // No proxy (the default): Paste cURL keeps its own Attach proxy select.
    expect(within(sections[0]).getByRole("combobox")).toHaveValue("");
    // Infloww's last resort: Select your role, then the alternative method.
    fireEvent.click(btn(/Still unable to perform verification/));
    expect(within(dialog()).getByText("Select your role")).toBeInTheDocument();
    fireEvent.click(within(dialog()).getByLabelText("Admin/employee"));
    fireEvent.click(btn("Next"));
    expect(within(dialog()).getByText("Linking OnlyFans account (Alternative method)")).toBeInTheDocument();
    fireEvent.click(btn("Back"));
    // Cancel goes back to the proxy step.
    fireEvent.click(btn("Cancel"));
    expect(within(dialog()).getByText("Proxy selection")).toBeInTheDocument();
  });

  it("offers three proxy choices with No proxy checked by default; Inflowwww proxy is disabled while the relay has no pool", async () => {
    renderWithProviders(<Page />);
    await open();
    details();
    fireEvent.click(btn("Next: Link creator account"));
    await within(dialog()).findByText("Which platform’s account would you like to link?");
    fireEvent.click(btn("Next"));
    const group = within(dialog()).getByRole("radiogroup", { name: "Proxy selection" });
    expect(within(group).getAllByRole("radio").map((r) => r.closest("label")!.querySelector("span > span")!.textContent))
      .toEqual(["Inflowwww proxy", "No proxy (server IP)", "Custom proxy"]);
    expect(within(group).getByRole("radio", { name: /^No proxy/ })).toBeChecked();
    await waitFor(() => expect(within(group).getByText("No Inflowwww proxies are set up on this server.")).toBeInTheDocument());
    expect(within(group).getByRole("radio", { name: /^Inflowwww proxy/ })).toBeDisabled();
    expect(btn("Connect OnlyFans")).toBeEnabled();
  });

  it("with a pool, Inflowwww proxy is the default, and Browserbase login starts on it with no proxy picker of its own", async () => {
    poolRelay();
    renderWithProviders(<Page />);
    await open();
    details();
    fireEvent.click(btn("Next: Link creator account"));
    await within(dialog()).findByText("Which platform’s account would you like to link?");
    fireEvent.click(btn("Next"));
    await waitFor(() => expect(within(dialog()).getByRole("radio", { name: /^Inflowwww proxy/ })).toBeChecked());
    fireEvent.click(btn("Connect OnlyFans"));
    const bb = await within(dialog()).findByRole("region", { name: "Browserbase login" });
    expect(within(bb).getByText("Proxy for this account:").parentElement).toHaveTextContent("Proxy for this account: Inflowwww proxy");
    expect(within(bb).queryByRole("combobox")).toBeNull();
    // Paste cURL binds the pool too: no Attach proxy select.
    expect(within(within(dialog()).getByRole("region", { name: "Paste cURL" })).queryByRole("combobox")).toBeNull();
    fireEvent.change(within(bb).getByLabelText("OnlyFans email"), { target: { value: "a@b.c" } });
    fireEvent.change(within(bb).getByLabelText("OnlyFans password"), { target: { value: "pw" } });
    fireEvent.click(within(bb).getByRole("button", { name: "Try Browserbase login" }));
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/login/remote/start", expect.objectContaining({
      backend: "browserbase", proxy: "infloww", nickname: "Nova",
    })));
  });

  /** A relay with a 3-proxy pool: `proxy-pool/assign` puts the account on it (or fails with `assignError`); the
   *  session reload fails `reloadFailures` times. */
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
      if (path === "/admin/automation/enqueue") return Promise.resolve({ enqueued_job_id: 42 });
      return Promise.resolve({ ok: true });
    });
  };
  /** Inflowwww proxy picked, then the sign-in step: the Paste cURL region. */
  const toPoolLogin = async () => {
    await open();
    details();
    fireEvent.click(btn("Next: Link creator account"));
    await within(dialog()).findByText("Which platform’s account would you like to link?");
    fireEvent.click(btn("Next"));
    const pool = within(dialog()).getByRole("radio", { name: /^Inflowwww proxy/ });
    await waitFor(() => expect(pool).toBeEnabled());
    fireEvent.click(pool);
    expect(within(dialog()).queryByRole("list", { name: "Proxies" })).toBeNull();
    expect(within(dialog()).queryByRole("link", { name: "New proxy" })).toBeNull();
    expect(btn("Connect OnlyFans")).toBeEnabled();
    fireEvent.click(btn("Connect OnlyFans"));
    return within(dialog()).findByRole("region", { name: "Paste cURL" });
  };
  const bootstrap = (paste: HTMLElement) => {
    fireEvent.change(within(paste).getByPlaceholderText(/^curl /), { target: { value: "curl 'https://onlyfans.com/api2/v2/x'" } });
    fireEvent.click(within(paste).getByRole("button", { name: "Bootstrap from cURL" }));
  };

  it("Inflowwww proxy hides the Attach proxy select, binds a pool proxy in the card's attach step, then the linked step reads the binding", async () => {
    poolRelay();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<Page />);
    const paste = await toPoolLogin();
    expect(within(paste).queryByRole("combobox")).toBeNull();
    expect(within(paste).queryByText("Attach proxy (optional)")).toBeNull();
    expect(within(paste).getByText(/Teleport warning:/)).toBeInTheDocument();
    bootstrap(paste);
    await within(dialog()).findByText("Creator account is linked to Inflowwww");
    // The attach step ran (bind, then reload) before the card handed the account to the flow.
    expect(confirm).toHaveBeenCalledTimes(1);
    const posts = relayPost.mock.calls.map(([p]) => String(p));
    expect(posts.indexOf("/admin/proxy-pool/assign")).toBeGreaterThan(posts.indexOf("/admin/session/bootstrap"));
    expect(posts.indexOf("/admin/reload-session?account_id=acct-new")).toBeGreaterThan(posts.indexOf("/admin/proxy-pool/assign"));
    expect(relayPost).toHaveBeenCalledWith("/admin/proxy-pool/assign", { account_id: "acct-new" });
    expect(relayPost).not.toHaveBeenCalledWith("/admin/proxies/assign", expect.anything());
    // Read back from GET /admin/proxies, which now lists the account on the pool.
    expect(await within(dialog()).findByText("Inflowwww proxy")).toBeInTheDocument();
    confirm.mockRestore();
  });

  it("a failed Inflowwww attach is shown in the card; Continue goes on, queues nothing, and the linked step reads No proxy", async () => {
    poolRelay(new Error("no Inflowwww proxies are set up on this relay"));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<Page />);
    const paste = await toPoolLogin();
    // Onboarding old fans moved to My Automations > Gen-Info: the card offers no such box.
    expect(within(paste).queryByLabelText(/Onboard the 100 most-recent subscribers/)).toBeNull();
    bootstrap(paste);
    expect(await within(paste).findByText(/but proxy attach failed:\s+no Inflowwww proxies are set up on this relay/)).toBeInTheDocument();
    expect(within(dialog()).queryByText("Creator account is linked to Inflowwww")).toBeNull();
    expect(relayPost).not.toHaveBeenCalledWith("/admin/reload-session?account_id=acct-new");
    expect(relayPost).not.toHaveBeenCalledWith("/admin/automation/enqueue", expect.anything(), expect.anything());
    fireEvent.click(within(paste).getByRole("button", { name: "Continue" }));
    await within(dialog()).findByText("Creator account is linked to Inflowwww");
    expect(relayPost).not.toHaveBeenCalledWith("/admin/automation/enqueue", expect.anything(), expect.anything());
    expect(await within(dialog()).findByText("No proxy (server IP)")).toBeInTheDocument();
    expect(within(dialog()).queryByText("Inflowwww proxy")).toBeNull();
    confirm.mockRestore();
  });

  it("when the bind worked but the session reload failed, the card says so and Retry finishes the attach", async () => {
    poolRelay(undefined, 1);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<Page />);
    const paste = await toPoolLogin();
    bootstrap(paste);
    expect(await within(paste).findByText(/the proxy is attached, but reloading the session failed:\s+relay 500\s+Press Retry/)).toBeInTheDocument();
    expect(within(paste).queryByText(/Change proxy/)).toBeNull();
    fireEvent.click(within(paste).getByRole("button", { name: "Retry" }));
    await within(dialog()).findByText("Creator account is linked to Inflowwww");
    expect(relayPost.mock.calls.filter(([p]) => p === "/admin/reload-session?account_id=acct-new")).toHaveLength(2);
    expect(await within(dialog()).findByText("Inflowwww proxy")).toBeInTheDocument();
    confirm.mockRestore();
  });

  it("the linked step shows an error, not a cached proxy, when the proxies read fails", async () => {
    poolRelay();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderWithProviders(<Page />);
    const paste = await toPoolLogin();
    proxies = () => Promise.reject(new RelayError(500, null, "relay 500"));
    bootstrap(paste);
    await within(dialog()).findByText("Creator account is linked to Inflowwww");
    expect(await within(dialog()).findByText("Couldn't read this account's proxy.")).toBeInTheDocument();
    expect(within(dialog()).queryByText("No proxy (server IP)")).toBeNull();
    expect(within(dialog()).queryByText("Inflowwww proxy")).toBeNull();
    confirm.mockRestore();
  });

  it("a custom proxy must pass its check before Connect OnlyFans, and the sign-in takes it", async () => {
    proxies = () => Promise.resolve({
      proxies: [{ label: "px-1", scheme: "http", host: "10.0.0.1", port: 8000, assigned_account_ids: [] }],
      pool: { size: 0, account_ids: [] }, accounts: [],
    });
    relayPost.mockImplementation((path: string) =>
      Promise.resolve(path === "/admin/proxies/px-1/test" ? { ok: true, ip: "10.0.0.1" } : {}));
    renderWithProviders(<Page />);
    await open();
    details();
    fireEvent.click(btn("Next: Link creator account"));
    await within(dialog()).findByText("Which platform’s account would you like to link?");
    fireEvent.click(btn("Next"));
    expect(within(dialog()).getByRole("radio", { name: /^No proxy/ })).toBeChecked();
    fireEvent.click(within(dialog()).getByRole("radio", { name: /^Custom proxy/ }));
    expect(btn("Connect OnlyFans")).toBeDisabled();
    fireEvent.click(await within(dialog()).findByRole("button", { name: "px-1 http 10.0.0.1:8000" }));
    await waitFor(() => expect(btn("Connect OnlyFans")).toBeEnabled());
    expect(relayPost).toHaveBeenCalledWith("/admin/proxies/px-1/test");
    expect(within(dialog()).getByRole("link", { name: "New proxy" })).toHaveAttribute("href", "/creators/proxy");
    fireEvent.click(btn("Connect OnlyFans"));
    const paste = await within(dialog()).findByRole("region", { name: "Paste cURL" });
    expect(within(paste).getByRole("combobox")).toHaveValue("px-1");
  });

  it("Fansly skips the proxy and signs in with the Fansly paste session", async () => {
    renderWithProviders(<Page />);
    await open();
    details();
    fireEvent.click(btn("Next: Link creator account"));
    fireEvent.click(await within(dialog()).findByLabelText("Fansly"));
    fireEvent.click(btn("Next"));
    expect(within(dialog()).getByText("Link Fansly account")).toBeInTheDocument();
    expect(within(dialog()).getAllByRole("region").map((s) => s.getAttribute("aria-label"))).toEqual(["Fansly paste session"]);
    expect(within(dialog()).getByRole("heading", { name: /^Connect Fansly/ })).toBeInTheDocument();
  });

  it("runs the extension probe once on mount with the unchanged URL, and the sign-in step reads its result", async () => {
    fetchMock.mockImplementation(() => Promise.resolve({ ok: true }));
    renderWithProviders(<Page />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(PROBE_URL, { method: "GET", cache: "no-store" });

    await toLogin();
    await waitFor(() => expect(within(dialog()).getByText(/Extension installed/)).toBeInTheDocument());
    fireEvent.click(btn("Close"));
    await open();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows Install Chrome Extension when the probe found no extension", async () => {
    renderWithProviders(<Page />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await toLogin();
    await waitFor(() => expect(within(dialog()).getByRole("link", { name: "Install Chrome Extension" })).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("puts Download app, a plain link to /download, right after the extension link on the web", async () => {
    renderWithProviders(<Page />);
    await toLogin();
    const ext = await within(dialog()).findByRole("link", { name: "Install Chrome Extension" });
    const download = within(dialog()).getByRole("link", { name: /Download app/ });
    expect(download).toHaveAttribute("href", "/download");
    expect(download).not.toHaveAttribute("target");
    expect(ext.nextElementSibling).toBe(download);
  });

  it("leaves Download app out inside the desktop app, so the extension link ends its row", async () => {
    (window as Window & { fasttShell?: { isDesktop: boolean } }).fasttShell = { isDesktop: true };
    try {
      renderWithProviders(<Page />);
      await toLogin();
      const ext = await within(dialog()).findByRole("link", { name: "Install Chrome Extension" });
      expect(within(dialog()).queryByRole("link", { name: /Download app/ })).toBeNull();
      expect(ext.nextElementSibling).toBeNull();
    } finally {
      delete (window as Window & { fasttShell?: unknown }).fasttShell;
    }
  });

  it("is reachable from the empty roster, and on a phone the sign-in is Browserbase login, Paste cURL desktop-only", async () => {
    renderWithProviders(<Page />);
    await screen.findByText("No data");
    await toLogin();
    // No extension on a phone: Paste cURL is hidden below md, Browserbase login (a remote browser) shows at every width.
    const paste = within(dialog()).getByRole("region", { name: "Paste cURL" }).parentElement!;
    expect(paste).toHaveClass("hidden", "md:block");
    const bb = within(dialog()).getByRole("region", { name: "Browserbase login" });
    expect(bb.closest(".hidden")).toBeNull();
    expect(within(bb).getByLabelText("OnlyFans email")).toBeInTheDocument();
    const line = within(dialog()).getByText("Paste cURL needs the desktop browser extension.");
    expect(line).toHaveClass("md:hidden");
    expect(paste).not.toContainElement(line);
    expect(within(dialog()).queryByText(/Session capture, proxies and keys are desktop-only/)).toBeNull();
  });

  it("captures through the same route, then Linked, Account details and success save the account's details", async () => {
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
    await toLogin();
    const paste = within(dialog()).getByRole("region", { name: "Paste cURL" });
    fireEvent.change(within(paste).getByPlaceholderText(/^curl /), { target: { value: "curl 'https://onlyfans.com/api2/v2/x'" } });
    fireEvent.click(within(paste).getByRole("button", { name: "Bootstrap from cURL" }));

    await within(dialog()).findByText("Creator account is linked to Inflowwww");
    expect(relayPost).toHaveBeenCalledWith("/admin/session/bootstrap", expect.objectContaining({ mode: "paste-curl", nickname: "Nova" }));
    expect(await within(dialog()).findByText("No proxy (server IP)")).toBeInTheDocument();
    expect(relayPost).not.toHaveBeenCalledWith("/admin/proxy-pool/assign", expect.anything());
    expect(within(dialog()).getByText("Step 2 of 3")).toBeInTheDocument();
    await waitFor(() => expect(relayGet.mock.calls.filter(([p]) => p === "/admin/accounts").length).toBeGreaterThanOrEqual(2));

    fireEvent.click(btn("Next"));
    expect(within(dialog()).getByText("Account details")).toBeInTheDocument();
    expect(within(dialog()).getByText("Step 3 of 3")).toBeInTheDocument();
    expect(within(dialog()).getByLabelText("Nickname")).toHaveValue("Nova");
    fireEvent.change(within(dialog()).getByLabelText("Tag (Optional)"), { target: { value: "VIP" } });
    fireEvent.change(within(dialog()).getByLabelText("Internal notes (Optional)"), { target: { value: "night shift" } });
    // Assigned employees: Emp Two can open every Creator, so it is checked and fixed.
    fireEvent.click(btn("Assigned employees"));
    const list = within(dialog()).getByRole("listbox");
    expect(within(list).getByRole("option", { name: /Emp Two/ })).toBeDisabled();
    fireEvent.click(within(list).getByRole("option", { name: "Emp One" }));
    fireEvent.click(btn("Next"));

    await within(dialog()).findByText("Creator account is linked to Inflowwww");
    expect(relayPatch).toHaveBeenCalledWith("/admin/accounts/acct-new", { nickname: "Nova" });
    expect(relayPut).toHaveBeenCalledWith("/admin/employees/1/access", { account_ids: ["acct-x", "acct-new"] });
    expect((settings as { creators: unknown }).creators).toEqual({
      drafts: [], // the Creator saved by step 1 is linked now
      profiles: { "acct-new": expect.objectContaining({ name: "Nova", gender: "Female", tag: "VIP", notes: "night shift" }) },
    });
    fireEvent.click(btn("Done"));
    expect(screen.queryByRole("dialog")).toBeNull();
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

    // creators-manage#23 / #40 labels.
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
    // In the table: the connectivity filter lists the label as an option (ticket 15).
    expect(within(table()).queryByText("Pending connection")).toBeNull();
    // The flag still outranks: it needs no health read to be known.
    expect(connCell("Dead")).toHaveTextContent(/^Disconnected/);
  });
});

describe("/creators — the footer pages the table on the client", () => {
  it("shows the total and pages 10 / 20 / 50 per page", async () => {
    accounts = Array.from({ length: 23 }, (_, i) => ({ id: `acct-${i + 1}`, nickname: `Model ${i + 1}` }));
    renderWithProviders(<Page />);
    await screen.findAllByText("Model 1");

    expect(screen.getByText("Total: 23 creators")).toBeInTheDocument(); // creators-manage#52
    expect(rows()).toHaveLength(10); // defaultPageSize:10
    // HB's pager (ticket 00's HbPager): prev is disabled on page 1.
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
      .toEqual(["10", "20", "50"]); // creators-manage#52
    fireEvent.click(per());
    size("20");
    expect(rows()).toHaveLength(20);
    expect(screen.getAllByText("Model 1")[0]).toBeInTheDocument();
    size("50");
    expect(rows()).toHaveLength(23);
  });

  it("shows the capture's No data and no footer when there are no Creators", async () => {
    renderWithProviders(<Page />);
    await screen.findByText("No data"); // creators-manage#50
    expect(screen.queryByText(/^Total:/)).toBeNull();
  });

  it("names a failed accounts read in the table body, titled as an extra, with no footer", async () => {
    relayGet.mockImplementation((path: string) =>
      path === "/admin/accounts" ? Promise.reject(new RelayError(500, null, "relay 500")) : Promise.resolve({}));
    renderWithProviders(<Page />);
    // The bundle has no error line in its table; the line is ours.
    expect(await within(table()).findByText("relay 500")).toHaveAttribute("title", EXTRA_LABEL);
    expect(screen.queryByText(/^Total:/)).toBeNull();
  });
});

// The footer sits at the page's foot (creators-manage#52, #53; the bundle's `_content-wrap` is a full-height column
// whose `_layout-wrap` scrolls above `_pagination-wrap`), so our extras sit above it, after the table.
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

  it("shows the drift banner above the footer, outside the disclosure and titled as an extra, only while a model is stale", async () => {
    accounts = [{ id: "acct-a", nickname: "Alpha" }];
    me = { is_admin: true }; // the disclosure is a Master's only
    drift = { any_drift: true, live_rev: "rev-2", accounts: [{ account_id: "acct-a", nickname: "Alpha", drift: true }] };
    const { unmount } = renderWithProviders(<Page />);
    const banner = (await screen.findByText("Session stale — re-capture required")).closest(`[title="${EXTRA_LABEL}"]`)!;
    expect(banner).not.toBeNull();
    expect(follows(table(), banner)).toBe(true);
    expect(follows(banner, screen.getByText("Total: 1 creators"))).toBe(true);
    expect(screen.getByText(EXTRAS_OVERFLOW_LABEL).closest("details")).not.toContainElement(banner as HTMLElement);
    unmount();

    drift = { any_drift: false, live_rev: "rev-2", accounts: [] };
    renderWithProviders(<Page />);
    await screen.findByText("Total: 1 creators");
    expect(screen.queryByText("Session stale — re-capture required")).toBeNull();
  });

  it("shows the mirror freshness alarm to the founder only", async () => {
    accounts = [{ id: "acct-a", nickname: "Alpha" }];
    drift = { any_drift: false, live_rev: "202612010900-abcdef0123", accounts: [] };
    me = { is_admin: true };
    const { unmount } = renderWithProviders(<Page />);
    await screen.findByText("OF Manager mirror is behind OnlyFans");
    unmount();

    me = { is_admin: false };
    renderWithProviders(<Page />);
    await screen.findByText("Total: 1 creators");
    await waitFor(() => expect(relayGet).toHaveBeenCalledWith("/admin/rev/drift"));
    expect(screen.queryByText("OF Manager mirror is behind OnlyFans")).toBeNull();
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
        { id: 2, display_name: "Emp Two", color: null, is_active: true, account_ids: null, chatter_id: "c2" }, // every Creator
        { id: 3, display_name: "Owner seat", color: null, is_active: true, account_ids: null, chatter_id: null },
      ],
    });
    renderWithProviders(<Page />);
    const col = () => within(table()).getAllByRole("columnheader").findIndex((h) => h.textContent === "Employees");
    const cell = (name: string) => within(rowOf(name)).getAllByRole("cell")[col()];
    await waitFor(() => expect(cell("Bravo")).toHaveTextContent("Emp One, Emp Two")); // creators-manage#38
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
      { id: "acct-a", nickname: "Alpha", has_session: true }, // the default Creator
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

    // creators-manage#45: a Connected row's Edit pencil sits outside the menu; it opens Edit account details.
    expect(within(rowOf("Bravo")).getByRole("button", { name: "Edit" })).toBeEnabled();

    const menu = openMenu("Bravo");
    // creators-manage#48, a Connected row (RenderActions): Link another account, Deactivate, Delete; then ours.
    expect(items(menu).map((i) => i.textContent)).toEqual([
      "Link another account", "Deactivate", "Delete", "Rename", "Make default",
    ]);
    // Deactivate opens its confirm (creators-manage#77; AccountsTable.test covers the modal).
    expect(within(menu).getByRole("menuitem", { name: "Deactivate" })).toBeEnabled();
    expect(within(menu).getByRole("menuitem", { name: "Link another account" })).toBeEnabled();
    expect(within(menu).getByRole("menuitem", { name: "Delete" })).toBeEnabled();
    // Each capture item leads with its icon (creators-manage#48: Edit04Line, PlusLine, UserX01Line, Trash01Line).
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

  it("Link another account opens the flow at the platform step with this platform taken", async () => {
    fleet();
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Bravo")).toHaveTextContent("Connected"));
    fireEvent.click(within(openMenu("Bravo")).getByRole("menuitem", { name: "Link another account" }));
    const d = screen.getByRole("dialog", { name: "Link creator account" });
    const of = within(d).getByLabelText("OnlyFans");
    expect(of).toBeDisabled();
    expect(of.closest("label")).toHaveAttribute("title", expect.stringContaining("already has an account from OnlyFans linked"));
    expect(within(d).getByLabelText("Fansly")).toBeChecked();
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
    fireEvent.click(within(d).getByRole("option", { name: "Emp One" })); // unassign
    fireEvent.click(within(d).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(relayPatch).toHaveBeenCalledWith("/admin/accounts/acct-b", { nickname: "Bravo B" });
    expect(relayPut).toHaveBeenCalledWith("/admin/employees/1/access", { account_ids: ["acct-c"] });
    expect((settings as { creators: { profiles: Record<string, unknown> } }).creators.profiles["acct-b"])
      .toEqual(expect.objectContaining({ name: "Bravo Creator", tag: "VIP" }));
    expect(screen.getByText("Update Success")).toBeInTheDocument();

    // Change proxy: unbind px-1, bind px-2, reload the session.
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

    // Bravo: on the pool → No proxy (pool unbind, reload).
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

    // Alpha: custom px-1 → Inflowwww proxy (the relay picks and binds; the account moves off px-1).
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

    // creators-manage#78: `DeleteCreatorsWithSurvey`, an HBModal (600px) with a two-step footer.
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

    // Infloww's message, then its survey (Optional); the answer has no Relay field, so it stays in the modal.
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

    // The default Creator is not offered Make default.
    expect(items(openMenu("Alpha")).map((i) => i.textContent)).not.toContain("Make default");
    // No Refresh session: it ran a server browser the relay does not ship; re-link with Paste cURL instead.
    expect(items(screen.getByRole("menu")).map((i) => i.textContent)).not.toContain("Refresh session");
  });

  it("each recovery action opens the Add creator modal at the section that performs it, or is Not wired", async () => {
    fleet();
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Charlie")).toHaveTextContent("Disconnected"));
    const dialog = () => screen.getByRole("dialog", { name: "Link creator account" });
    const close = () => fireEvent.click(within(dialog()).getByRole("button", { name: "Close" }));

    // A Connected row offers no link button and no recovery (creators-manage#45).
    expect(within(rowOf("Bravo")).queryByRole("button", { name: "Link creator account" })).toBeNull();
    expect(items(openMenu("Bravo")).map((i) => i.textContent)).not.toContain("Log in to account via OnlyFans");
    fireEvent.mouseDown(document.body);

    // creators-manage#46, #58: any other row's link button, "Link creator account", opens at Paste cURL (the
    // extension path, the owner's first way in), titled as the capture's later steps are (#56).
    fireEvent.click(within(rowOf("Charlie")).getByRole("button", { name: "Link creator account" }));
    expect(within(dialog()).getByRole("region", { name: "Paste cURL" })).toHaveFocus();
    close();

    // creators-manage#46, #48: the row's menu holds Edit first, then the capture's three; the recovery actions follow.
    const menu = openMenu("Charlie");
    expect(items(menu).map((i) => i.textContent)).toEqual([
      "Edit", "Link another account", "Deactivate", "Delete",
      "Log in to account via OnlyFans", "Log in to account via Login+",
      "Rename", "Make default",
    ]);
    expect(within(menu).getByRole("menuitem", { name: "Edit" })).toBeEnabled();
    // Login+ is Infloww's phone app.
    const loginPlus = within(menu).getByRole("menuitem", { name: "Log in to account via Login+" });
    expect(loginPlus).toBeDisabled();
    expect(loginPlus).toHaveAttribute("title", "not wired");
    fireEvent.mouseDown(document.body); // an outside click closes the menu

    // #59, re-link: the OnlyFans sign-in opens at Paste cURL (no password sign-in on the relay).
    fireEvent.click(within(openMenu("Charlie")).getByRole("menuitem", { name: "Log in to account via OnlyFans" }));
    expect(within(dialog()).getByRole("region", { name: "Paste cURL" })).toHaveFocus();
    close();
    expect(screen.queryByRole("dialog")).toBeNull();
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
    const paste = within(d).getByRole("region", { name: "Paste cURL" });
    // A re-login keeps the account's proxy: Browserbase login binds nothing either.
    const bb = within(d).getByRole("region", { name: "Browserbase login" });
    expect(within(bb).getByText("Proxy for this account:").parentElement).toHaveTextContent("unchanged");
    fireEvent.change(within(paste).getByPlaceholderText(/^curl /), { target: { value: "curl 'https://onlyfans.com/api2/v2/x'" } });
    fireEvent.click(within(paste).getByRole("button", { name: "Bootstrap from cURL" }));
    await within(d).findByText("Creator account is linked to Inflowwww");
    expect(await within(d).findByText("Inflowwww proxy")).toBeInTheDocument();
    expect(relayPost).not.toHaveBeenCalledWith("/admin/proxy-pool/assign", expect.anything());
  });

  it("a re-login through Browserbase sends No proxy, so the relay keeps the account's binding", async () => {
    fleet();
    proxies = () => Promise.resolve({ proxies: [], pool: { size: 2, account_ids: ["acct-c"] }, accounts: [] });
    relayPost.mockImplementation(() => Promise.resolve({}));
    renderWithProviders(<Page />);
    await waitFor(() => expect(connCell("Charlie")).toHaveTextContent("Disconnected"));
    fireEvent.click(within(openMenu("Charlie")).getByRole("menuitem", { name: "Log in to account via OnlyFans" }));
    const bb = within(screen.getByRole("dialog", { name: "Link creator account" })).getByRole("region", { name: "Browserbase login" });
    fireEvent.change(within(bb).getByLabelText("OnlyFans email"), { target: { value: "a@b.c" } });
    fireEvent.change(within(bb).getByLabelText("OnlyFans password"), { target: { value: "pw" } });
    fireEvent.click(within(bb).getByRole("button", { name: "Try Browserbase login" }));
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
