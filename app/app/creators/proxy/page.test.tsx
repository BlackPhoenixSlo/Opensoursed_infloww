/**
 * The `/creators/proxy` route reads like its Layout capture, `docs/infloww-layouts/creators-proxy.md`
 * (docs/spec/infloww-parity-round-2/phase-04-creators-pages.md, Testing Decisions, Custom proxy page; ticket 17):
 * the title, "+ Add new proxy", the seven columns, "No data", 10 rows a page, the two status labels, and the
 * row actions; then the Add new proxy modal, with the label defaulting to host:port and the bulk paste inside it
 * (ticket 18); then the Creator egress table under it (ticket 19). The Relay client is mocked; labels, hosts (TEST-NET addresses) and Creators are invented.
 */
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/lib/relay", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/relay")>();
  return { ...real, relay: { get: vi.fn(), delete: vi.fn(), post: vi.fn() } };
});

import Page from "@/app/creators/proxy/page";
import { relay, RelayError } from "@/lib/relay";
import { EXTRA_LABEL } from "@/lib/openinflowwwwExtras";
import { renderWithProviders } from "@/test-utils";

const relayGet = relay.get as unknown as Mock;
const relayPost = relay.post as unknown as Mock;
const relayDelete = relay.delete as unknown as Mock;

type P = {
  label: string; scheme: string; host: string; port: number;
  verified_ip?: string | null; verified_at?: string | null;
  assigned_accounts?: Array<{ id: string; nickname?: string | null }>;
};
const proxy = (label: string, over: Partial<P> = {}): P => ({
  label, scheme: "http", host: "192.0.2.10", port: 8000, verified_ip: null, verified_at: null,
  assigned_accounts: [], ...over,
});
const ACCOUNTS: Array<{ id: string; nickname: string; has_session?: boolean }> = [
  { id: "acc-a", nickname: "Creator A" },
  { id: "acc-b", nickname: "Creator B" },
  { id: "acc-c", nickname: "Creator C" },
];

function serve(proxies: P[], accounts = ACCOUNTS) {
  relayGet.mockImplementation(async (path: string) => {
    if (path === "/admin/proxies") return { proxies, accounts };
    throw new Error(`unmocked ${path}`);
  });
}

/** The proxy table, the page's first; the Creator egress table follows it (ticket 19). */
const proxyTable = () => screen.getAllByRole("table")[0];
/** The table row whose first cell reads `label` (the Proxy label, or the Creator in the egress table). */
function rowOf(label: string, table: HTMLElement = proxyTable()): HTMLElement {
  const cell = within(table).getAllByRole("cell").find((c) => c.textContent === label);
  if (!cell) throw new Error(`no row ${label}`);
  return cell.closest("tr") as HTMLElement;
}
/** The cell of `row` under its own table's header `name`. */
function cellOf(row: HTMLElement, name: string): HTMLElement {
  const heads = within(row.closest("table") as HTMLElement).getAllByRole("columnheader").map((h) => h.textContent);
  return within(row).getAllByRole("cell")[heads.indexOf(name)];
}
const bodyLabels = () =>
  within(proxyTable()).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0].textContent);

beforeEach(() => {
  relayGet.mockReset();
  relayPost.mockReset();
  relayDelete.mockReset();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("/creators/proxy", () => {
  it("shows the capture's title, add button and column headers", async () => {
    serve([proxy("px-1")]);
    renderWithProviders(<Page />);
    // creators-proxy#3: the page title; #7: the header button.
    expect(screen.getByRole("heading", { name: "Manage your custom proxies" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Add new proxy" })).toBeInTheDocument();
    await screen.findByText("px-1");
    expect(within(proxyTable()).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Proxy label", // creators-proxy#11
      "Host", // creators-proxy#12
      "Port", // creators-proxy#12
      "Type", // creators-proxy#12
      "Creator", // creators-proxy#13
      "Proxy status", // creators-proxy#14
      "Actions", // creators-proxy#16
    ]);
    // page-parity 03: antd dark's filled head row (#1e1e1e on #151515) with a 22px divider after every head cell but
    // the last, and the antd dark row rule.
    const headRow = within(proxyTable()).getAllByRole("row")[0];
    expect(headRow).toHaveClass("bg-white/4");
    const heads = within(headRow).getAllByRole("columnheader");
    expect(heads.filter((h) => h.classList.contains("after:bg-white/6"))).toHaveLength(6);
    expect(heads[heads.length - 1]).not.toHaveClass("after:bg-white/6");
    expect(rowOf("px-1")).toHaveClass("border-white/6");
    // Full width: the header rule runs edge to edge, as Infloww's does (no 1800px cap).
    const root = screen.getByRole("heading", { name: "Manage your custom proxies" }).closest("header")!.parentElement!;
    expect(root).not.toHaveClass("max-w-shell");
    expect(document.querySelector(".max-w-shell")).toBeNull();
    // The Proxies card, its heading and its old columns are gone.
    expect(screen.queryByRole("heading", { name: "Proxies" })).toBeNull();
    expect(screen.queryByText("Bound to")).toBeNull();
  });

  it("fills a row's cells from the proxies read, with the bundle's type words", async () => {
    serve([
      proxy("px-http", { host: "192.0.2.11", port: 8080 }),
      proxy("px-socks", { scheme: "socks5", host: "192.0.2.12", port: 1080 }),
      proxy("px-https", { scheme: "https", host: "192.0.2.13", port: 443 }),
    ]);
    renderWithProviders(<Page />);
    await screen.findByText("px-http");
    const r = rowOf("px-http");
    expect(cellOf(r, "Host").textContent).toBe("192.0.2.11");
    expect(cellOf(r, "Port").textContent).toBe("8080");
    // creators-proxy#12: http and socks; the relay's https is ours.
    expect(cellOf(r, "Type").textContent).toBe("http");
    expect(cellOf(rowOf("px-socks"), "Type").textContent).toBe("socks");
    const https = within(cellOf(rowOf("px-https"), "Type")).getByText("https");
    expect(https.closest("[title]")?.getAttribute("title")).toContain(EXTRA_LABEL);
  });

  it("shows No data on an empty registry, with no pager", async () => {
    serve([]);
    renderWithProviders(<Page />);
    // creators-proxy#20: antd's simple empty, ticket 00's EmptyState with its drawn tray, "No data" #595959.
    const empty = await screen.findByText("No data");
    expect(empty).toHaveClass("text-[#595959]");
    expect(within(proxyTable()).getByRole("cell").querySelector("svg[data-empty-art]")).not.toBeNull();
    expect(screen.queryByRole("navigation", { name: "Pagination" })).toBeNull();
  });

  it("pages the table at 10 rows a page", async () => {
    const labels = Array.from({ length: 23 }, (_, i) => `px-${String(i + 1).padStart(2, "0")}`);
    serve(labels.map((l) => proxy(l)));
    renderWithProviders(<Page />);
    await screen.findByText("px-01");
    // creators-proxy#23: 10 a page.
    expect(bodyLabels()).toEqual(labels.slice(0, 10));
    const pager = screen.getByRole("navigation", { name: "Pagination" });
    fireEvent.click(within(pager).getByRole("button", { name: "2" }));
    expect(bodyLabels()).toEqual(labels.slice(10, 20));
    // antd's current page: a 1px primary outline, primary text, no fill, 6px corners.
    expect(within(pager).getByRole("button", { name: "2" })).toHaveClass("border", "border-accent", "text-accent", "bg-transparent", "rounded-md", "h-8", "min-w-8");
    fireEvent.click(within(pager).getByRole("button", { name: "Next page" }));
    expect(bodyLabels()).toEqual(labels.slice(20));
    expect(within(pager).getByRole("button", { name: "Next page" })).toBeDisabled();
    fireEvent.click(within(pager).getByRole("button", { name: "Previous page" }));
    expect(bodyLabels()).toEqual(labels.slice(10, 20));
  });

  it("maps verified, unverified and failed-test proxies to the capture's two status labels", async () => {
    serve([
      proxy("px-ok", { verified_ip: "198.51.100.7", verified_at: "2026-10-17T10:00:00Z" }),
      proxy("px-new"),
      proxy("px-bad", { verified_ip: "198.51.100.8", verified_at: "2026-10-17T10:00:00Z" }),
    ]);
    relayPost.mockResolvedValue({ ok: false, error: "connect timeout" });
    renderWithProviders(<Page />);
    await screen.findByText("px-ok");
    // creators-proxy#14: the first state for a working proxy, the second otherwise.
    expect(within(cellOf(rowOf("px-ok"), "Proxy status")).getByText("Available")).toBeInTheDocument();
    expect(within(cellOf(rowOf("px-new"), "Proxy status")).getByText("Unavailable")).toBeInTheDocument();
    expect(within(cellOf(rowOf("px-bad"), "Proxy status")).getByText("Available")).toBeInTheDocument();
    // The latest test outranks the stored verification.
    fireEvent.click(within(rowOf("px-bad")).getByRole("button", { name: "Test" }));
    await waitFor(() =>
      expect(within(cellOf(rowOf("px-bad"), "Proxy status")).getByText("Unavailable")).toBeInTheDocument(),
    );
    // The verified IP and the test error stay beside the label, as ours.
    const ip = within(cellOf(rowOf("px-ok"), "Proxy status")).getByText("198.51.100.7");
    expect(ip.getAttribute("title")).toContain(EXTRA_LABEL);
    const err = within(cellOf(rowOf("px-bad"), "Proxy status")).getByText("connect timeout");
    expect(err.getAttribute("title")).toContain(EXTRA_LABEL);
  });

  it("a passing test turns an unverified proxy Available", async () => {
    serve([proxy("px-new")]);
    // The route's own answer (service/proxies.py `probe`): the egress IP is `ip`.
    relayPost.mockResolvedValue({ ok: true, ip: "198.51.100.9", geo: null, error: null });
    renderWithProviders(<Page />);
    await screen.findByText("px-new");
    fireEvent.click(within(rowOf("px-new")).getByRole("button", { name: "Test" }));
    await waitFor(() =>
      expect(within(cellOf(rowOf("px-new"), "Proxy status")).getByText("Available")).toBeInTheDocument(),
    );
    expect(within(cellOf(rowOf("px-new"), "Proxy status")).getByText("198.51.100.9")).toBeInTheDocument();
  });

  it("keeps Bind, Unbind, Test and Remove on today's routes, labelling the extras", async () => {
    serve([
      proxy("px-free"),
      proxy("px-shared", { assigned_accounts: [{ id: "acc-a", nickname: "Creator A" }, { id: "acc-b", nickname: "Creator B" }] }),
    ]);
    relayPost.mockResolvedValue({ ok: true });
    relayDelete.mockResolvedValue({ ok: true });
    renderWithProviders(<Page />);
    await screen.findByText("px-free");

    // Bind: the assign select in the Creator cell.
    const bind = within(cellOf(rowOf("px-free"), "Creator")).getByRole("combobox");
    expect(bind.getAttribute("title")).toContain(EXTRA_LABEL);
    fireEvent.change(bind, { target: { value: "acc-c" } });
    await waitFor(() =>
      expect(relayPost).toHaveBeenCalledWith("/admin/proxies/assign", { label: "px-free", account_id: "acc-c" }),
    );

    // Unbind: the × on a Creator chip.
    const unbind = within(rowOf("px-shared")).getByRole("button", { name: "Unbind Creator A" });
    expect(unbind.getAttribute("title")).toContain(EXTRA_LABEL);
    fireEvent.click(unbind);
    await waitFor(() =>
      expect(relayPost).toHaveBeenCalledWith("/admin/proxies/px-shared/unbind", { account_id: "acc-a" }),
    );

    // The shared-egress warning stays, as ours.
    const shared = within(rowOf("px-shared")).getByText("shared egress");
    expect(shared.closest("[title]")?.getAttribute("title")).toContain(EXTRA_LABEL);

    // Test, ours, in Actions.
    const test = within(cellOf(rowOf("px-free"), "Actions")).getByRole("button", { name: "Test" });
    expect(test.getAttribute("title")).toContain(EXTRA_LABEL);
    fireEvent.click(test);
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/proxies/px-free/test"));

    // creators-proxy#16: Edit is Not wired (the relay cannot rename a proxy).
    const edit = within(cellOf(rowOf("px-free"), "Actions")).getByRole("button", { name: "Edit" });
    expect(edit).toBeDisabled();
    expect(edit).toHaveAttribute("title", "not wired");

    // creators-proxy#16: Delete is the capture's, shown only while no Creator is bound.
    expect(within(rowOf("px-shared")).queryByRole("button", { name: "Delete" })).toBeNull();
    const del = within(cellOf(rowOf("px-free"), "Actions")).getByRole("button", { name: "Delete" });
    expect(del.getAttribute("title") ?? "").not.toContain(EXTRA_LABEL);
    fireEvent.click(del);
    fireEvent.click(within(screen.getByRole("dialog", { name: "Delete proxy" })).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(relayDelete).toHaveBeenCalledWith("/admin/proxies/px-free"));
  });

  it("asks before Delete in the capture's modal, not the browser's confirm", async () => {
    serve([proxy("px-free")]);
    relayDelete.mockResolvedValue({ ok: true });
    const confirmSpy = vi.spyOn(window, "confirm");
    renderWithProviders(<Page />);
    await screen.findByText("px-free");
    const del = () => within(cellOf(rowOf("px-free"), "Actions")).getByRole("button", { name: "Delete" });

    // creators-proxy#38: the title, the question, then Cancel and the danger Delete.
    fireEvent.click(del());
    let m = screen.getByRole("dialog", { name: "Delete proxy" });
    expect(within(m).getByText("Are you sure you want to delete this proxy?")).toBeInTheDocument();
    expect(within(m).getAllByRole("button").map((b) => b.textContent)).toEqual(["Cancel", "Delete"]);
    fireEvent.click(within(m).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    // Escape closes it too (antd's keyboard default).
    fireEvent.click(del());
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(relayDelete).not.toHaveBeenCalled();

    fireEvent.click(del());
    m = screen.getByRole("dialog", { name: "Delete proxy" });
    fireEvent.click(within(m).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(relayDelete).toHaveBeenCalledWith("/admin/proxies/px-free"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("shows placeholder rows, not No data, while the proxies read runs", async () => {
    relayGet.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<Page />);
    // creators-proxy#22 drew antd's spinner over an empty table; the owner's 2026-10-29 ask is placeholder rows on
    // every page, and no false "No data" before the first answer.
    expect(proxyTable().querySelectorAll("tbody [data-loading]").length).toBeGreaterThan(0);
    expect(within(proxyTable()).queryByText("No data")).toBeNull();
    expect(screen.queryByText(/Loading proxies/)).toBeNull();
  });

  it("folds long page runs and offers the size changer past 50 proxies, as antd's pager does", async () => {
    const labels = Array.from({ length: 120 }, (_, i) => `px-${String(i + 1).padStart(3, "0")}`);
    serve(labels.map((l) => proxy(l)));
    renderWithProviders(<Page />);
    await screen.findByText("px-001");
    const pager = screen.getByRole("navigation", { name: "Pagination" });
    // creators-proxy#23 (rc-pagination, 2 pages each side): 12 pages fold after page 5.
    const items = () =>
      within(pager).getAllByRole("button")
        .filter((b) => !/^(Previous|Next) page$/.test(b.getAttribute("aria-label") ?? ""))
        .map((b) => b.textContent);
    expect(items()).toEqual(["1", "2", "3", "4", "5", "•••", "12"]);
    fireEvent.click(within(pager).getByRole("button", { name: "Next 5 Pages" }));
    expect(bodyLabels()).toEqual(labels.slice(50, 60));
    expect(items()).toEqual(["1", "•••", "4", "5", "6", "7", "8", "•••", "12"]);
    fireEvent.click(within(pager).getByRole("button", { name: "Previous 5 Pages" }));
    expect(bodyLabels()).toEqual(labels.slice(0, 10));

    // More than 50 rows: the size changer, 10 / 20 / 50 / 100 a page, 10 first.
    const size = within(pager).getByRole("combobox", { name: "Page size" }) as HTMLSelectElement;
    expect(Array.from(size.options).map((o) => o.textContent)).toEqual(["10 / page", "20 / page", "50 / page", "100 / page"]);
    expect(size.value).toBe("10");
    fireEvent.change(size, { target: { value: "50" } });
    expect(bodyLabels()).toEqual(labels.slice(0, 50));
    expect(items()).toEqual(["1", "2", "3"]);
  });

  it("offers no size changer at 50 proxies or fewer", async () => {
    serve(Array.from({ length: 50 }, (_, i) => proxy(`px-${i + 1}`)));
    renderWithProviders(<Page />);
    await screen.findByText("px-1");
    const pager = screen.getByRole("navigation", { name: "Pagination" });
    expect(within(pager).queryByRole("combobox")).toBeNull();
  });

  it("a chatter refused the proxies read sees its controls not wired and no error banner", async () => {
    relayGet.mockRejectedValue(new RelayError(403, { detail: "owner only" }, "owner only"));
    renderWithProviders(<Page />);
    const add = screen.getByRole("button", { name: "+ Add new proxy" });
    await waitFor(() => expect(add).toHaveAttribute("title", "not wired"));
    expect(add).toBeDisabled();
    // The form and the paste box live in the modal (ticket 18), which the disabled button cannot open.
    fireEvent.click(add);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByLabelText("Paste proxies (one per line)")).toBeNull();
    expect(screen.queryByText("owner only")).toBeNull();
    expect(screen.queryByText(/Loading proxies/)).toBeNull();
  });
});

/** Opens the Add new proxy modal and returns it. */
async function openAdd(): Promise<HTMLElement> {
  const add = screen.getByRole("button", { name: "+ Add new proxy" });
  await waitFor(() => expect(add).toBeEnabled());
  fireEvent.click(add);
  return screen.getByRole("dialog", { name: "Add new proxy" });
}
const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });

describe("/creators/proxy — Add new proxy", () => {
  it("opens the capture's modal from + Add new proxy; the form is not on the page until then", async () => {
    serve([proxy("px-1")]);
    renderWithProviders(<Page />);
    await screen.findByText("px-1");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByLabelText("Proxy label")).toBeNull();
    expect(screen.queryByLabelText("Paste proxies (one per line)")).toBeNull();
    const m = await openAdd();
    // creators-proxy#28 to #33: the capture's fields, in its order.
    expect(within(m).getByLabelText("Proxy label")).toBeInTheDocument();
    // #29: Type radios http and socks, none chosen at first; https is ours.
    const radios = within(m).getAllByRole("radio") as HTMLInputElement[];
    expect(radios.map((r) => r.closest("label")?.textContent)).toEqual(["http", "socks", "https"]);
    expect(radios.every((r) => !r.checked)).toBe(true);
    expect(radios[2].closest("[title]")?.getAttribute("title")).toContain(EXTRA_LABEL);
    expect(within(m).getByLabelText("IP address")).toBeInTheDocument();
    expect(within(m).getByLabelText("Port")).toHaveAttribute("placeholder", "e.g. 80");
    expect(within(m).getByLabelText("Username")).toBeInTheDocument();
    expect(within(m).getByLabelText("Password")).toHaveAttribute("type", "password");
    // Ours, after the capture's fields: Notes, the storage hint and the IP address field's hostnames.
    expect(within(m).getByLabelText(/^Notes/).closest("div")?.querySelector(`[title="${EXTRA_LABEL}"]`)).not.toBeNull();
    expect(within(m).getByText(/stored in/).closest("[title]")?.getAttribute("title")).toBe(EXTRA_LABEL);
    expect(within(m).getByLabelText("IP address").getAttribute("title")).toContain(EXTRA_LABEL);
    // #27: Cancel, then Add proxy, off until the form is valid.
    expect(within(m).getByRole("button", { name: "Add proxy" })).toBeDisabled();
    fireEvent.click(within(m).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("defaults the label to host:port, saves through POST /admin/proxies and closes", async () => {
    serve([proxy("px-1")]);
    relayPost.mockResolvedValue({ ok: true, proxy: {} });
    renderWithProviders(<Page />);
    await screen.findByText("px-1");
    const m = await openAdd();
    const label = within(m).getByLabelText("Proxy label") as HTMLInputElement;
    // The label field and its host:port default are ours: the relay keys a proxy by its label.
    expect(label.getAttribute("title")).toContain(EXTRA_LABEL);
    type(within(m).getByLabelText("IP address"), "192.0.2.20");
    type(within(m).getByLabelText("Port"), "8080");
    expect(label.value).toBe("192.0.2.20:8080");
    fireEvent.click(within(m).getByRole("radio", { name: "socks" }));
    type(within(m).getByLabelText("Username"), "user-a");
    type(within(m).getByLabelText("Password"), "pw-a");
    const save = within(m).getByRole("button", { name: "Add proxy" });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() =>
      expect(relayPost).toHaveBeenCalledWith("/admin/proxies", {
        label: "192.0.2.20:8080", scheme: "socks5", host: "192.0.2.20", port: 8080,
        username: "user-a", password: "pw-a", notes: "",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps an edited label when host or port changes after", async () => {
    serve([]);
    relayPost.mockResolvedValue({ ok: true, proxy: {} });
    renderWithProviders(<Page />);
    await screen.findByText("No data");
    const m = await openAdd();
    const label = within(m).getByLabelText("Proxy label") as HTMLInputElement;
    type(within(m).getByLabelText("IP address"), "192.0.2.21");
    type(label, "px edited");
    type(within(m).getByLabelText("Port"), "3128");
    expect(label.value).toBe("px edited");
    fireEvent.click(within(m).getByRole("radio", { name: "http" }));
    fireEvent.click(within(m).getByRole("button", { name: "Add proxy" }));
    await waitFor(() =>
      expect(relayPost).toHaveBeenCalledWith("/admin/proxies", expect.objectContaining({
        label: "px edited", scheme: "http", host: "192.0.2.21", port: 3128,
      })),
    );
  });

  it("checks the proxy through Test before keeping it, and a failed check removes it and shows a toast", async () => {
    serve([]);
    relayPost.mockImplementation(async (path: string) =>
      path === "/admin/proxies" ? { ok: true, proxy: {} } : { ok: false, ip: null, error: "connect timeout" },
    );
    relayDelete.mockResolvedValue({ ok: true });
    renderWithProviders(<Page />);
    await screen.findByText("No data");
    const m = await openAdd();
    fireEvent.click(within(m).getByRole("radio", { name: "http" }));
    type(within(m).getByLabelText("IP address"), "192.0.2.40");
    type(within(m).getByLabelText("Port"), "3128");
    fireEvent.click(within(m).getByRole("button", { name: "Add proxy" }));
    // creators-proxy#37: the check runs on the new proxy; the Relay probes only a registered label.
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/proxies/192.0.2.40%3A3128/test"));
    await waitFor(() => expect(relayDelete).toHaveBeenCalledWith("/admin/proxies/192.0.2.40%3A3128"));
    // #27: the failure is antd's message toast, and the modal stays open.
    const toast = await screen.findByRole("alert");
    expect(toast.textContent).toContain("Proxy check failed: connect timeout");
    expect(within(m).queryByText(/connect timeout/)).toBeNull();
    expect(screen.getByRole("dialog", { name: "Add new proxy" })).toBeInTheDocument();
  });

  it("closes once the check passes, keeping the proxy", async () => {
    serve([]);
    relayPost.mockImplementation(async (path: string) =>
      path === "/admin/proxies" ? { ok: true, proxy: {} } : { ok: true, ip: "198.51.100.40", error: null },
    );
    renderWithProviders(<Page />);
    await screen.findByText("No data");
    const m = await openAdd();
    fireEvent.click(within(m).getByRole("radio", { name: "http" }));
    type(within(m).getByLabelText("IP address"), "192.0.2.41");
    type(within(m).getByLabelText("Port"), "3128");
    fireEvent.click(within(m).getByRole("button", { name: "Add proxy" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(relayPost).toHaveBeenCalledWith("/admin/proxies/192.0.2.41%3A3128/test");
    expect(relayDelete).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
    // #37: `message.success` after the add.
    expect(screen.getByRole("status").textContent).toContain("Proxy added");
  });

  it("shows a refused save as a toast, not a line in the footer", async () => {
    serve([]);
    relayPost.mockRejectedValue(new Error("port out of range (1-65535)"));
    renderWithProviders(<Page />);
    await screen.findByText("No data");
    const m = await openAdd();
    fireEvent.click(within(m).getByRole("radio", { name: "http" }));
    type(within(m).getByLabelText("IP address"), "192.0.2.42");
    type(within(m).getByLabelText("Port"), "3128");
    fireEvent.click(within(m).getByRole("button", { name: "Add proxy" }));
    expect((await screen.findByRole("alert")).textContent).toContain("port out of range (1-65535)");
    expect(within(m).queryByText(/out of range/)).toBeNull();
  });

  it("closes on Escape and reveals the password on demand", async () => {
    serve([]);
    renderWithProviders(<Page />);
    await screen.findByText("No data");
    let m = await openAdd();
    // creators-proxy#33: Input.Password's visibility toggle.
    const pw = within(m).getByLabelText("Password") as HTMLInputElement;
    expect(pw.type).toBe("password");
    fireEvent.click(within(m).getByRole("button", { name: "Show password" }));
    expect(pw.type).toBe("text");
    fireEvent.click(within(m).getByRole("button", { name: "Hide password" }));
    expect(pw.type).toBe("password");
    // #24: antd's keyboard default closes the modal on Escape; the mask still does not.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    m = await openAdd();
    expect(m).toBeInTheDocument();
  });

  it("keeps port 0 not wired, as the Relay takes 1–65535", async () => {
    serve([]);
    renderWithProviders(<Page />);
    await screen.findByText("No data");
    const m = await openAdd();
    fireEvent.click(within(m).getByRole("radio", { name: "http" }));
    type(within(m).getByLabelText("IP address"), "192.0.2.43");
    type(within(m).getByLabelText("Port"), "0");
    const save = within(m).getByRole("button", { name: "Add proxy" });
    // creators-proxy#32: the bundle's field takes 0; the Relay refuses it.
    expect(save).toBeDisabled();
    expect(save.getAttribute("title")).toMatch(/^not wired: port 0/);
  });

  it("refuses a duplicate label before sending", async () => {
    serve([proxy("192.0.2.10:8000")]);
    renderWithProviders(<Page />);
    await screen.findByText("192.0.2.10:8000");
    const m = await openAdd();
    fireEvent.click(within(m).getByRole("radio", { name: "http" }));
    type(within(m).getByLabelText("IP address"), "192.0.2.10");
    type(within(m).getByLabelText("Port"), "8000");
    expect(within(m).getByText('A proxy named "192.0.2.10:8000" already exists')).toBeInTheDocument();
    const save = within(m).getByRole("button", { name: "Add proxy" });
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(relayPost).not.toHaveBeenCalled();
  });

  it("keeps Add proxy off until the proxy list has loaded, so the duplicate guard can run", async () => {
    relayGet.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<Page />);
    const m = await openAdd();
    fireEvent.click(within(m).getByRole("radio", { name: "http" }));
    type(within(m).getByLabelText("IP address"), "192.0.2.10");
    type(within(m).getByLabelText("Port"), "8000");
    const save = within(m).getByRole("button", { name: "Add proxy" });
    expect(save).toBeDisabled();
    expect(save.getAttribute("title")).toMatch(/^not wired/);
  });

  it("holds the bulk paste as an Inflowwww extra, posting the bulk add with Added N and the line errors", async () => {
    serve([]);
    const text = "192.0.2.30:8000\nnot a proxy";
    relayPost.mockResolvedValue({
      added: [{ label: "192.0.2.30:8000", host: "192.0.2.30", port: 8000, scheme: "https" }],
      errors: [{ line: 2, text_redacted: "not a proxy", reason: "unrecognised format" }],
    });
    renderWithProviders(<Page />);
    await screen.findByText("No data");
    const m = await openAdd();
    const box =within(m).getByLabelText("Paste proxies (one per line)");
    expect(box.closest(`[title="${EXTRA_LABEL}"]`)).not.toBeNull();
    expect(within(m).getAllByText(EXTRA_LABEL).length).toBeGreaterThan(0);
    type(box, text);
    fireEvent.change(within(m).getByLabelText("Scheme"), { target: { value: "https" } });
    fireEvent.click(within(m).getByRole("button", { name: "Add all" }));
    await waitFor(() => expect(within(m).getByText(/Added 1/)).toBeInTheDocument());
    expect(relayPost).toHaveBeenCalledWith("/admin/proxies/bulk", { text, scheme: "https" });
    expect(within(m).getByText(/Line 2: unrecognised format/)).toBeInTheDocument();
    // The modal stays open on the result.
    expect(screen.getByRole("dialog", { name: "Add new proxy" })).toBeInTheDocument();
  });
});

describe("/creators/proxy — Creator egress", () => {
  const egressTable = () => screen.getByRole("table", { name: "Creator egress" });

  it("lists one row per Creator with the bound proxy's verified IP or No custom proxy, and its session", async () => {
    serve(
      [
        proxy("px-a", {
          verified_ip: "198.51.100.7", verified_at: "2026-10-17T10:00:00Z",
          assigned_accounts: [{ id: "acc-a", nickname: "Creator A" }],
        }),
        proxy("px-b", { assigned_accounts: [{ id: "acc-b", nickname: "Creator B" }] }),
        proxy("px-free"),
      ],
      [
        { id: "acc-a", nickname: "Creator A", has_session: true },
        { id: "acc-b", nickname: "Creator B", has_session: false },
        { id: "acc-c", nickname: "Creator C", has_session: true },
      ],
    );
    renderWithProviders(<Page />);
    await waitFor(() => rowOf("px-a"));
    const t = egressTable();
    expect(within(t).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Creator", "Creator ID", "Egress", "Session", "Action",
    ]);
    // One row per Creator, in the accounts' order.
    expect(within(t).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0].textContent))
      .toEqual(["Creator A", "Creator B", "Creator C"]);
    const a = rowOf("Creator A", t);
    expect(cellOf(a, "Creator ID").textContent).toBe("acc-a");
    expect(within(cellOf(a, "Egress")).getByText("198.51.100.7")).toBeInTheDocument();
    expect(cellOf(a, "Session").textContent).toBe("Has session");
    // A bound proxy that was never verified has no IP yet, but it is still a custom proxy.
    const b = rowOf("Creator B", t);
    expect(within(cellOf(b, "Egress")).queryByText("No custom proxy")).toBeNull();
    expect(within(cellOf(b, "Egress")).getByText("px-b")).toBeInTheDocument();
    expect(cellOf(b, "Session").textContent).toBe("No session");
    // An unbound Creator leaves from the relay's own IP: nothing to test.
    const c = rowOf("Creator C", t);
    expect(cellOf(c, "Egress").textContent).toBe("No custom proxy");
    expect(within(cellOf(c, "Action")).getByRole("button", { name: "Test" })).toBeDisabled();
    // The capture has no such table (creators-proxy.md, Notes): the whole section is ours.
    const section = t.closest("section") as HTMLElement;
    expect(section.getAttribute("title")).toBe(EXTRA_LABEL);
    expect(within(section).getByText(EXTRA_LABEL)).toBeInTheDocument();
    // A pure view over the one proxies read: no other relay read.
    expect(relayGet.mock.calls.map((call) => call[0])).toEqual(["/admin/proxies"]);
  });

  it("marks the automatic per-Creator proxy not wired where an unbound Creator shows No custom proxy", async () => {
    serve([proxy("px-1", { assigned_accounts: [{ id: "acc-a", nickname: "Creator A" }] })]);
    renderWithProviders(<Page />);
    await screen.findAllByText("px-1");
    // creators-proxy#40, #41: the bundle gives each Creator an automatic proxy; the Relay has none.
    const none = within(screen.getAllByRole("table")[1]).getAllByText("No custom proxy")[0];
    expect(none.getAttribute("title")).toMatch(/^not wired: /);
  });

  it("its Test posts the proxy test for the bound label and shows the egress IP", async () => {
    serve([proxy("px-a", { assigned_accounts: [{ id: "acc-a", nickname: "Creator A" }] })]);
    // The route's own answer (service/proxies.py `probe`): the egress IP is `ip`.
    relayPost.mockResolvedValue({ ok: true, ip: "198.51.100.9", geo: null, error: null });
    renderWithProviders(<Page />);
    await waitFor(() => rowOf("px-a"));
    const t = egressTable();
    const test = within(cellOf(rowOf("Creator A", t), "Action")).getByRole("button", { name: "Test" });
    expect(test).toBeEnabled();
    fireEvent.click(test);
    await waitFor(() => expect(relayPost).toHaveBeenCalledWith("/admin/proxies/px-a/test"));
    await waitFor(() =>
      expect(within(cellOf(rowOf("Creator A", t), "Egress")).getByText("198.51.100.9")).toBeInTheDocument(),
    );
  });
});
