/**
 * The Settings layout (app/app/settings/layout.tsx) rendered as a component:
 * the Settings header with "Settings" and the ✕ that leaves Settings (the
 * "Desktop app" link moved to About), and the Tab list under it; then the Panel parts every
 * Settings tab is built from (docs/spec/settings-tabs/phase-00-shell-tokens-blob.md).
 */
import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BlobNotes,
  Card,
  Field,
  FieldInput,
  FieldSelect,
  FieldTextarea,
  NotAppliedYet,
  NotWired,
  RadioGroup,
  Section,
  SettingsPanel,
  ToggleRow,
} from "@/components/settings/SettingsPanel";
import { renderWithProviders } from "@/test-utils";

const back = vi.fn();
const push = vi.fn();
vi.mock("next/navigation", () => ({
  usePathname: () => "/settings/account",
  useRouter: () => ({ back, push }),
}));
// The session: an Agency owner unless a test signs in a Chatter only.
let session: { user: { username: string; is_admin?: boolean } | null; chatter: { username: string } | null };
vi.mock("@/contexts/UserContext", () => ({ useUser: () => ({ user: session.user }) }));
vi.mock("@/contexts/ChatterContext", () => ({ useChatter: () => ({ chatter: session.chatter }) }));

import Layout from "@/app/settings/layout";

const renderLayout = () =>
  renderWithProviders(
    <Layout>
      <p>panel</p>
    </Layout>,
  );

const historyLength = (n: number) => vi.spyOn(History.prototype, "length", "get").mockReturnValue(n);

beforeEach(() => {
  session = { user: { username: "tester" }, chatter: null };
  back.mockClear();
  push.mockClear();
});
const shell = window as Window & { fasttShell?: { isDesktop: boolean } };
afterEach(() => {
  vi.restoreAllMocks();
  delete shell.fasttShell;
});

describe("Settings header", () => {
  it("reads Settings, keeps the Desktop app link (a plain anchor to /download), and holds the panel", () => {
    renderLayout();
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Desktop app/ });
    expect(link).toHaveAttribute("href", "/download");
    expect(link).not.toHaveAttribute("target");
    expect(screen.getByText("panel")).toBeInTheDocument();
  });

  it("leaves the Desktop app link out inside the desktop app", () => {
    shell.fasttShell = { isDesktop: true };
    renderLayout();
    expect(screen.queryByRole("link", { name: /Desktop app/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Close settings" })).toBeInTheDocument();
  });

  it("✕ goes back once when there is history", () => {
    historyLength(2);
    renderLayout();
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
    expect(back).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
  });

  it("✕ goes to / when Settings was opened with no history", () => {
    historyLength(1);
    renderLayout();
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
    expect(push).toHaveBeenCalledWith("/");
    expect(back).not.toHaveBeenCalled();
  });
});

// The 14 Settings tabs in nav order (docs/infloww-screens.md §3.10, plus Co-creator tag, AI keys and the Audit log).
const SETTINGS = [
  "/settings/account",
  "/settings/preferences",
  "/settings/security-org",
  "/settings/security-personal",
  "/settings/billing",
  "/settings/balance",
  "/settings/roles",
  "/settings/sales",
  "/settings/time-tracking",
  "/settings/messaging",
  "/settings/cotag",
  "/settings/ai-keys",
  "/settings/audit",
  "/settings/about",
];
const BLOB = ["account", "preferences", "roles", "sales", "time-tracking", "messaging"].map((t) => `/settings/${t}`);

const rows = () => Array.from(document.querySelectorAll<HTMLAnchorElement>('[data-settings="tab"]'));
const hrefs = () => rows().map((r) => r.getAttribute("href"));

describe("Tab list", () => {
  it("lists the 14 Settings tabs in nav order, each with an icon", () => {
    renderLayout();
    expect(hrefs()).toEqual(SETTINGS);
    for (const r of rows()) expect(r.querySelector("svg")).not.toBeNull();
  });

  it("adds the System tab after About for the master only", () => {
    session = { user: { username: "master", is_admin: true }, chatter: null };
    renderLayout();
    expect(hrefs()).toEqual([...SETTINGS, "/settings/system"]);
  });

  it("marks only the current tab's row aria-current=page", () => {
    renderLayout();
    const current = rows().filter((r) => r.getAttribute("aria-current") === "page");
    expect(current.map((r) => r.getAttribute("href"))).toEqual(["/settings/account"]);
  });

  it("leaves the six Blob tabs, Security (organization), Co-creator tag, AI keys and the Audit log out for a Chatter-only session", () => {
    session = { user: null, chatter: { username: "fixture-chatter" } };
    renderLayout();
    expect(hrefs()).toEqual(
      SETTINGS.filter((h) => !BLOB.includes(h) && h !== "/settings/cotag" && h !== "/settings/ai-keys" && h !== "/settings/security-org" && h !== "/settings/audit"),
    );
    expect(hrefs()).toHaveLength(4);
  });

  it("refuses a Chatter-only session a hidden tab opened by URL, and shows it to the owner", () => {
    session = { user: null, chatter: { username: "fixture-chatter" } };
    const { unmount } = renderLayout();
    expect(screen.queryByText("panel")).toBeNull();
    expect(screen.getByText("Your role does not allow this page")).toBeInTheDocument();
    unmount();
    session = { user: { username: "tester" }, chatter: null };
    renderLayout();
    expect(screen.getByText("panel")).toBeInTheDocument();
  });
});

describe("Panel parts", () => {
  it("SettingsPanel puts its title in the Panel header and its children in the Panel body", () => {
    renderWithProviders(
      <SettingsPanel title="Account" actions={<button type="button">Edit</button>}>
        <p>body text</p>
      </SettingsPanel>,
    );
    const header = document.querySelector('[data-settings="panel-header"]') as HTMLElement;
    const body = document.querySelector('[data-settings="panel-body"]') as HTMLElement;
    expect(within(header).getByRole("heading", { name: "Account" })).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(within(body).getByText("body text")).toBeInTheDocument();
    expect(within(header).queryByText("body text")).toBeNull();
  });

  it("Section renders its title as a heading above its children", () => {
    renderWithProviders(
      <Section title="Personal info">
        <p>child</p>
      </Section>,
    );
    const heading = screen.getByRole("heading", { name: "Personal info" });
    const child = screen.getByText("child");
    expect(heading.compareDocumentPosition(child) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("Section without a title renders its children and no heading", () => {
    renderWithProviders(
      <Section>
        <p>child</p>
      </Section>,
    );
    expect(screen.getByText("child")).toBeInTheDocument();
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("FieldInput forwards value, onChange and disabled to an input", () => {
    const onChange = vi.fn();
    renderWithProviders(
      <>
        <FieldInput aria-label="Agency name" value="Alpha One" onChange={onChange} />
        <FieldInput aria-label="Locked" value="Beta Two" disabled onChange={vi.fn()} />
      </>,
    );
    const input = screen.getByRole("textbox", { name: "Agency name" });
    expect(input).toHaveValue("Alpha One");
    fireEvent.change(input, { target: { value: "Gamma Three" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(input).toBeEnabled();
    expect(screen.getByRole("textbox", { name: "Locked" })).toBeDisabled();
  });

  it("FieldTextarea forwards value, onChange, rows and disabled to a textarea", () => {
    const onChange = vi.fn();
    renderWithProviders(
      <>
        <FieldTextarea aria-label="Prompt" value="Alpha One" rows={6} onChange={onChange} />
        <FieldTextarea aria-label="Locked" value="Beta Two" disabled onChange={vi.fn()} />
      </>,
    );
    const box = screen.getByRole("textbox", { name: "Prompt" });
    expect(box.tagName).toBe("TEXTAREA");
    expect(box).toHaveValue("Alpha One");
    expect(box).toHaveAttribute("rows", "6");
    fireEvent.change(box, { target: { value: "Gamma Three" } });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(box).toBeEnabled();
    expect(screen.getByRole("textbox", { name: "Locked" })).toBeDisabled();
  });

  it("FieldSelect forwards value, onChange and disabled and renders exactly the given options", () => {
    const onChange = vi.fn();
    const options = [
      { value: "alpha", label: "Alpha One" },
      { value: "beta", label: "Beta Two" },
    ] as const;
    renderWithProviders(
      <>
        <FieldSelect aria-label="Pick" value="alpha" options={options} onChange={onChange} />
        <FieldSelect aria-label="Locked" value="beta" options={options} onChange={vi.fn()} disabled />
      </>,
    );
    const select = screen.getByRole("combobox", { name: "Pick" });
    expect(select).toHaveTextContent("Alpha One");
    fireEvent.keyDown(select, { key: "Enter" });
    const list = screen.getByRole("listbox", { name: "Pick" });
    expect(within(list).getAllByRole("option").map((o) => [o.getAttribute("aria-selected"), o.textContent])).toEqual([
      ["true", "Alpha One"],
      ["false", "Beta Two"],
    ]);
    fireEvent.click(within(list).getByRole("option", { name: "Beta Two" }));
    expect(onChange).toHaveBeenCalledWith("beta");
    expect(select).toBeEnabled();
    expect(screen.getByRole("combobox", { name: "Locked" })).toBeDisabled();
  });

  it("RadioGroup renders one radio per option in its rows, checks the value, and calls onChange with the typed value", () => {
    const onChange = vi.fn();
    const options = [
      { value: "alpha", label: "Alpha One" },
      { value: "beta", label: "Beta Two" },
      { value: "gamma", label: "Gamma Three" },
    ] as const;
    renderWithProviders(
      <RadioGroup aria-label="Pick" name="pick" value="beta" options={options} onChange={onChange} rowClassName="row-x" />,
    );
    const radios = within(screen.getByRole("radiogroup", { name: "Pick" })).getAllByRole("radio");
    expect(radios.map((r) => [r.closest("label")?.textContent, r.closest("label")?.className, r.getAttribute("name")])).toEqual([
      ["Alpha One", "row-x", "pick"],
      ["Beta Two", "row-x", "pick"],
      ["Gamma Three", "row-x", "pick"],
    ]);
    expect(radios.map((r) => (r as HTMLInputElement).checked)).toEqual([false, true, false]);
    fireEvent.click(screen.getByRole("radio", { name: "Gamma Three" }));
    expect(onChange).toHaveBeenCalledWith("gamma");
  });

  it("NotWired is disabled with title \"not wired\" and a click calls nothing", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderWithProviders(<NotWired label="Change password" />);
    const button = screen.getByRole("button", { name: "Change password" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "not wired");
    fireEvent.click(button);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.queryByText(/saved/i)).toBeNull();
  });

  it("ToggleRow with notWired is a disabled switch; without it a click flips the value", () => {
    const on = vi.fn();
    renderWithProviders(
      <>
        <ToggleRow title="Two-factor authentication" notWired />
        <ToggleRow title="Dark mode" description="Use the dark theme" checked={false} onChange={on} />
      </>,
    );
    const twoFa = screen.getByRole("switch", { name: "Two-factor authentication" });
    expect(twoFa).toBeDisabled();
    expect(twoFa).toHaveAttribute("title", "not wired");
    expect(twoFa).toHaveAttribute("aria-checked", "false");
    const dark = screen.getByRole("switch", { name: "Dark mode" });
    expect(dark).toHaveAttribute("aria-checked", "false");
    fireEvent.click(dark);
    expect(on).toHaveBeenCalledWith(true);
    expect(screen.getByText("Use the dark theme")).toBeInTheDocument();
  });

  it("Card puts its title and control in one row above its body, and without either renders only the body", () => {
    renderWithProviders(
      <>
        <Card title="Clock-in reminder" control={<button type="button">Toggle</button>}>
          <p>Card body</p>
        </Card>
        <Card>
          <p>Bare body</p>
        </Card>
      </>,
    );
    const row = screen.getByText("Clock-in reminder").parentElement as HTMLElement;
    expect(within(row).getByRole("button", { name: "Toggle" })).toBeInTheDocument();
    expect(row.nextElementSibling).toBe(screen.getByText("Card body"));
    const bare = screen.getByText("Bare body");
    expect(bare.parentElement?.children).toHaveLength(1);
    expect(bare.parentElement?.className).toContain("border-[var(--if-line)]");
  });

  it("a filled Card draws the 1cat4 box on --if-card-bg, its icon before the title", () => {
    renderWithProviders(
      <Card box="filled" title="AI translation" icon={<svg data-testid="icon" />}>
        <p>Caption</p>
      </Card>,
    );
    const title = screen.getByText("AI translation");
    expect(title.firstElementChild).toBe(screen.getByTestId("icon"));
    const box = screen.getByText("Caption").parentElement as HTMLElement;
    expect(box.className.split(" ")).toEqual(["mt-4", "px-4", "py-3", "rounded-[12px]", "bg-[var(--if-card-bg)]"]);
  });

  it("Field labels its input", () => {
    renderWithProviders(
      <Field label="Username" htmlFor="username">
        <FieldInput id="username" value="tester" readOnly />
      </Field>,
    );
    expect(screen.getByLabelText("Username")).toHaveValue("tester");
  });

  it("NotAppliedYet says the ADR-0008 sentence", () => {
    renderWithProviders(<NotAppliedYet />);
    expect(screen.getByText("Saved for your organization; not applied yet.")).toBeInTheDocument();
  });

  it("BlobNotes shows the gate note, and Retry only once the load failed", () => {
    const q = { isFetching: false, refetch: vi.fn() };
    const { rerender } = renderWithProviders(<BlobNotes note={{ text: "Still waiting", failed: false }} q={q} />);
    expect(screen.queryByText(/not applied yet/)).toBeNull();
    expect(screen.getByText("Still waiting")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();

    rerender(<BlobNotes note={null} q={q} />);
    expect(screen.queryByText("Still waiting")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();

    rerender(<BlobNotes note={{ text: "Never loaded", failed: true }} q={q} />);
    expect(screen.getByText("Never loaded")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(q.refetch).toHaveBeenCalledTimes(1);
  });
});
