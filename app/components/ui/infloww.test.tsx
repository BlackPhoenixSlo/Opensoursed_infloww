import { useState } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderWithProviders } from "@/test-utils";
import type { AccountMeta } from "@/lib/relay";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/growth/scripts",
  useSearchParams: () => new URLSearchParams(),
}));

import {
  EmptyState, HB_TABLE, HbButton, HbFilter, HbModal, HbPager, HbSelect, IF_TABLE, IfBody, IfButton, IfCard,
  IfCreatorSelect, IfInput, IfLearn, IfModal, IfPager, IfRangePicker, IfSegmented, IfSelect, IfSwitch, IfTabs,
  InflowwPageHeader, useCreatorParam,
} from "./infloww";
import { PageFrame } from "@/components/shell/PageFrame";

beforeEach(() => {
  replace.mockClear();
  window.history.replaceState(null, "", "/growth/scripts");
});

describe("InflowwPageHeader", () => {
  it("renders one h1, the extra slot and the actions", () => {
    render(
      <InflowwPageHeader title="Scripts" extra={<span>creator pick</span>} actions={<button type="button">New</button>} />,
    );
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Scripts");
    expect(screen.getByText("creator pick")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New" })).toBeInTheDocument();
  });

  it("is the 48px bar with the L1 rule", () => {
    render(<InflowwPageHeader title="Scripts" />);
    const bar = screen.getByRole("banner");
    expect(bar).toHaveClass("h-12", "px-6", "bg-bg", "border-b", "border-border");
    expect(screen.getByRole("heading", { level: 1 })).toHaveClass("text-[16px]", "font-semibold");
  });

  it("shows the report time zone with its tooltip when utc is given", () => {
    render(<InflowwPageHeader title="Dashboard" utc="UTC" />);
    expect(screen.getByText("UTC+00:00")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Set by your organization" })).toBeInTheDocument();
  });

  it("draws a Back control and the medium weight when asked", async () => {
    const onBack = vi.fn();
    render(<InflowwPageHeader title="Notifications" onBack={onBack} weight="medium" />);
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(onBack).toHaveBeenCalledOnce();
    expect(screen.getByRole("heading", { level: 1 })).toHaveClass("font-medium");
  });
});

describe("PageFrame", () => {
  it("renders the Infloww header then a full-width p-4 body", () => {
    render(<PageFrame title="Manage employees"><p>body</p></PageFrame>);
    expect(screen.getByRole("heading", { level: 1, name: "Manage employees" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveClass("h-12");
    const body = screen.getByText("body").parentElement!;
    expect(body).toHaveClass("p-4");
    expect(body.className).not.toMatch(/max-w-shell/);
  });

  it("passes extra and actions to the header", () => {
    render(
      <PageFrame title="Auto Post" extra={<span>creator pick</span>} actions={<button type="button">New auto post</button>}>
        <p>body</p>
      </PageFrame>,
    );
    const bar = screen.getByRole("banner");
    expect(within(bar).getByText("creator pick")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "New auto post" })).toBeInTheDocument();
    expect(within(bar).queryByText("body")).toBeNull();
  });
});

describe("EmptyState", () => {
  it("renders the decorative SVG and the text", () => {
    const { container } = render(<EmptyState text="No employees have clocked in." />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("height", "100");
    expect(screen.getByText("No employees have clocked in.")).toHaveClass("text-muted");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("sizes the art 40px for sm and 90px for md", () => {
    const { container, rerender } = render(<EmptyState size="sm" />);
    expect(container.querySelector("svg")).toHaveAttribute("height", "40");
    expect(screen.getByText("No data")).toBeInTheDocument();
    rerender(<EmptyState size="md" />);
    expect(container.querySelector("svg")).toHaveAttribute("height", "90");
  });

  it("draws the kind's art", () => {
    const { container } = render(<EmptyState kind="search" text="No results" />);
    expect(container.querySelector("svg")).toHaveAttribute("data-empty-art", "search");
  });

  it("kind=error renders Retry and calls onRetry", async () => {
    const onRetry = vi.fn();
    render(<EmptyState kind="error" text="Request failed" onRetry={onRetry} />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("renders an action below the text", () => {
    render(<EmptyState text="No lists" action={<button type="button">Create list</button>} />);
    expect(screen.getByRole("button", { name: "Create list" })).toBeInTheDocument();
  });
});

describe("IfCard", () => {
  it("renders the title with its info tip and the extra", () => {
    render(<IfCard title="My shifts" info="Your shifts this week" extra={<span>x</span>}><p>c</p></IfCard>);
    expect(screen.getByRole("heading", { level: 2, name: /My shifts/ })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Your shifts this week" })).toBeInTheDocument();
    const card = screen.getByText("c").parentElement!;
    expect(card).toHaveClass("bg-bg-elev-1", "rounded-[12px]");
    expect(card.className).not.toMatch(/\bborder\b/);
  });
});

describe("buttons", () => {
  it("HbButton primary is the orange fill with black text; sm is 28px", () => {
    const { rerender } = render(<HbButton>Add creator</HbButton>);
    expect(screen.getByRole("button")).toHaveClass("bg-cta", "text-black", "h-9", "rounded-[4px]");
    rerender(<HbButton variant="secondary" size="sm">Cancel</HbButton>);
    expect(screen.getByRole("button")).toHaveClass("h-7");
    expect(screen.getByRole("button")).toHaveAttribute("type", "button");
  });

  it("IfButton variants and its icon", () => {
    const Icon = (p: { className?: string }) => <svg data-testid="icon" {...p} />;
    const { rerender } = render(<IfButton variant="primary" icon={Icon as never}>New Message</IfButton>);
    expect(screen.getByRole("button")).toHaveClass("bg-accent", "h-8", "rounded-md");
    expect(screen.getByTestId("icon")).toBeInTheDocument();
    rerender(<IfButton>Cancel</IfButton>);
    expect(screen.getByRole("button")).toHaveClass("border", "border-border");
    rerender(<IfButton size="lg">Add media</IfButton>);
    expect(screen.getByRole("button")).toHaveClass("h-9");
  });

  it("IfLearn links out in a new tab", () => {
    render(<IfLearn href="https://help.example/x" />);
    const a = screen.getByRole("link", { name: "Learn" });
    expect(a).toHaveAttribute("href", "https://help.example/x");
    expect(a).toHaveAttribute("target", "_blank");
  });

  it("IfLearn with no href is a disabled, not wired button that keeps the book and the M1 colour", () => {
    render(<IfLearn />);
    const b = screen.getByRole("button", { name: "Learn" });
    expect(b).toBeDisabled();
    expect(b).toHaveAttribute("title", "not wired");
    expect(b).toHaveClass("text-accent", "disabled:opacity-50");
    expect(b.querySelector("svg.lucide-book-open")).toBeInTheDocument();
  });

  it("IfLearn with a tip opens it in a popover; Escape and an outside click close it", async () => {
    render(<><IfLearn tip="Posts on a schedule." /><p>outside</p></>);
    const b = screen.getByRole("button", { name: "Learn" });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    await userEvent.click(b);
    expect(b).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("note")).toHaveTextContent("Posts on a schedule.");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    await userEvent.click(b);
    await userEvent.click(screen.getByText("outside"));
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});

const OPTS = [
  { value: "net", label: "Net earnings" },
  { value: "gross", label: "Gross earnings" },
];

function SelectHarness({ searchable }: { searchable?: boolean }) {
  const [v, setV] = useState("net");
  return <IfSelect aria-label="Earnings" value={v} options={OPTS} onChange={setV} searchable={searchable} />;
}

describe("IfSelect", () => {
  it("opens on Enter and closes on Escape", async () => {
    render(<SelectHarness />);
    const trigger = screen.getByRole("combobox", { name: "Earnings" });
    trigger.focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("moves with the arrows and picks with Enter", async () => {
    render(<SelectHarness />);
    const trigger = screen.getByRole("combobox", { name: "Earnings" });
    expect(trigger).toHaveTextContent("Net earnings");
    trigger.focus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(trigger).toHaveTextContent("Gross earnings");
  });

  it("picks on click and marks the selected option", async () => {
    render(<SelectHarness />);
    await userEvent.click(screen.getByRole("combobox"));
    expect(screen.getByRole("option", { name: "Net earnings" })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("option", { name: "Gross earnings" }));
    expect(screen.getByRole("combobox")).toHaveTextContent("Gross earnings");
  });

  it("searchable filters the options", async () => {
    render(<SelectHarness searchable />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.type(screen.getByRole("textbox", { name: "Search" }), "gro");
    expect(screen.getAllByRole("option")).toHaveLength(1);
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("combobox")).toHaveTextContent("Gross earnings");
  });

  it("closes on an outside click", async () => {
    render(<><SelectHarness /><p>outside</p></>);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByText("outside"));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("HbSelect and HbFilter", () => {
  it("HbSelect wears the HB filter look", async () => {
    const onChange = vi.fn();
    render(<HbSelect aria-label="Platform" value={null} placeholder="Platform" options={OPTS} onChange={onChange} />);
    const trigger = screen.getByRole("combobox", { name: "Platform" });
    expect(trigger).toHaveClass("h-7", "bg-[#161616]", "border-0");
    expect(trigger).toHaveTextContent("Platform");
    await userEvent.click(trigger);
    await userEvent.click(screen.getByRole("option", { name: "Gross earnings" }));
    expect(onChange).toHaveBeenCalledWith("gross");
  });

  it("HbFilter is a class string for inputs", () => {
    expect(HbFilter).toContain("bg-[#161616]");
    expect(HbFilter).toContain("placeholder:text-[#a6a6a6]");
  });
});

describe("IfInput", () => {
  it("forwards the input props and draws the search icon", async () => {
    const onChange = vi.fn();
    const { container } = render(<IfInput search placeholder="Search name" onChange={onChange} className="w-[320px]" />);
    const input = screen.getByPlaceholderText("Search name");
    await userEvent.type(input, "a");
    expect(onChange).toHaveBeenCalled();
    expect(container.firstElementChild).toHaveClass("w-[320px]", "h-8");
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});

describe("IfRangePicker", () => {
  it("emits both ends", () => {
    const onChange = vi.fn();
    const { rerender } = render(<IfRangePicker from="" to="" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-10-01" } });
    expect(onChange).toHaveBeenLastCalledWith({ from: "2026-10-01", to: "" });
    rerender(<IfRangePicker from="2026-10-01" to="" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: "2026-10-19" } });
    expect(onChange).toHaveBeenLastCalledWith({ from: "2026-10-01", to: "2026-10-19" });
  });

  it("is a labelled group whose empty ends show antd's placeholders until focused", () => {
    render(<><label htmlFor="r">Date created:</label><IfRangePicker id="r" onChange={() => {}} /></>);
    const from = screen.getByLabelText("Date created:") as HTMLInputElement;
    expect(from.closest("[role=group]")).toBeInTheDocument();
    expect(from.type).toBe("text");
    expect(from).toHaveAttribute("placeholder", "Start date");
    fireEvent.focus(from);
    expect(from.type).toBe("date");
    fireEvent.blur(from);
    expect(from.type).toBe("text");
  });

  it("disabled dims the box and titles both ends", () => {
    render(<IfRangePicker disabled title="not wired" />);
    for (const name of ["Start date", "End date"]) {
      const end = screen.getByRole("textbox", { name });
      expect(end).toBeDisabled();
      expect(end).toHaveAttribute("title", "not wired");
    }
    expect(screen.getByRole("group")).toHaveClass("opacity-50");
  });
});

const TABS = [
  { value: "auto", label: "Automated Messages" },
  { value: "manual", label: "Manual" },
  { value: "drafts", label: "Drafts" },
];

describe("IfTabs", () => {
  function Harness() {
    const [v, setV] = useState("auto");
    return <IfTabs aria-label="Messages" tabs={TABS} value={v} onChange={setV} extra={<button type="button">Create</button>} />;
  }

  it("moves with the arrow keys and marks aria-selected", async () => {
    render(<Harness />);
    const [auto, manual, drafts] = screen.getAllByRole("tab");
    expect(auto).toHaveAttribute("aria-selected", "true");
    expect(manual).toHaveAttribute("aria-selected", "false");
    auto.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(manual).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(manual).toHaveAttribute("aria-selected", "true");
    expect(auto).toHaveAttribute("aria-selected", "false");
    await userEvent.keyboard("{ArrowRight}{ArrowRight}");
    expect(auto).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(drafts).toHaveFocus();
    await userEvent.keyboard(" ");
    expect(drafts).toHaveAttribute("aria-selected", "true");
  });

  it("renders the extra slot outside the tablist", () => {
    render(<Harness />);
    const create = screen.getByRole("button", { name: "Create" });
    expect(within(screen.getByRole("tablist")).queryByRole("button", { name: "Create" })).not.toBeInTheDocument();
    expect(create).toBeInTheDocument();
  });

  it("idPrefix ties each tab to its panel id", () => {
    render(<IfTabs idPrefix="sm" tabs={TABS} value="auto" onChange={() => {}} />);
    const [auto, manual] = screen.getAllByRole("tab");
    expect(auto).toHaveAttribute("id", "sm-tab-auto");
    expect(auto).toHaveAttribute("aria-controls", "sm-panel-auto");
    expect(manual).toHaveAttribute("aria-controls", "sm-panel-manual");
  });
});

describe("IfSegmented", () => {
  it("marks the active option and reports a pick", async () => {
    const onChange = vi.fn();
    render(<IfSegmented aria-label="Period" value="week" onChange={onChange}
      options={[{ value: "today", label: "Today" }, { value: "week", label: "This week" }]} />);
    expect(screen.getByRole("radio", { name: "This week" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "This week" })).toHaveClass("text-accent", "bg-bg-elev-2");
    await userEvent.click(screen.getByRole("radio", { name: "Today" }));
    expect(onChange).toHaveBeenCalledWith("today");
  });
});

describe("IfSwitch", () => {
  it("toggles by click and by Space, with role=switch", async () => {
    function Harness() {
      const [on, setOn] = useState(false);
      return <IfSwitch label="Auto-reply" checked={on} onChange={setOn} />;
    }
    render(<Harness />);
    const sw = screen.getByRole("switch", { name: "Auto-reply" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    await userEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "true");
    sw.focus();
    await userEvent.keyboard(" ");
    expect(sw).toHaveAttribute("aria-checked", "false");
  });

  it("is disabled while loading", () => {
    render(<IfSwitch aria-label="Sync" checked loading onChange={() => {}} />);
    expect(screen.getByRole("switch", { name: "Sync" })).toBeDisabled();
  });
});

describe("IfPager", () => {
  it("prints the total, marks the current page and pages", async () => {
    const onPage = vi.fn();
    render(<IfPager total={45} page={1} size={10} onPage={onPage} />);
    const nav = screen.getByRole("navigation", { name: "Pagination" });
    expect(nav).toHaveTextContent("Total: 45 records");
    expect(screen.getByRole("button", { name: "Page 1" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Page 3" }));
    expect(onPage).toHaveBeenCalledWith(3);
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(onPage).toHaveBeenCalledWith(2);
  });

  it("elides long ranges", () => {
    render(<IfPager total={500} page={25} size={10} onPage={() => {}} />);
    const pages = screen.getAllByRole("button", { name: /^Page / }).map((b) => b.textContent);
    expect(pages).toEqual(["1", "23", "24", "25", "26", "27", "50"]);
  });
});

describe("HbPager", () => {
  it("disables prev on page 1 and next on the last page", () => {
    const { rerender } = render(
      <HbPager total={25} noun="creators" page={1} size={10} onPage={() => {}} onSize={() => {}} />,
    );
    expect(screen.getByText("Total: 25 creators")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled();
    rerender(<HbPager total={25} noun="creators" page={3} size={10} onPage={() => {}} onSize={() => {}} />);
    expect(screen.getByRole("button", { name: "Previous page" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("offers 10 / 20 / 50 per page", async () => {
    const onSize = vi.fn();
    render(<HbPager total={1} noun="creators" page={1} size={10} onPage={() => {}} onSize={onSize} />);
    const per = screen.getByRole("combobox", { name: "Per page" });
    expect(per).toHaveTextContent("10");
    await userEvent.click(per);
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["10", "20", "50"]);
    await userEvent.click(screen.getByRole("option", { name: "20" }));
    expect(onSize).toHaveBeenCalledWith(20);
  });
});

describe("tables and body", () => {
  it("exposes the class sets", () => {
    expect(HB_TABLE.th).toContain("bg-panel");
    expect(HB_TABLE.row).toContain("border-[#2c2c2c]");
    expect(HB_TABLE.fixedAction).toContain("sticky");
    expect(IF_TABLE.th).toContain("bg-bg-elev-2");
    expect(IF_TABLE.th).toContain("h-[46px]");
    expect(IF_TABLE.thDivider).toContain("before:h-[22px]");
    expect(IF_TABLE.fixedRight).toContain("w-[100px]");
  });

  it("IfBody is padding 16px 24px", () => {
    render(<IfBody>b</IfBody>);
    expect(screen.getByText("b")).toHaveClass("px-6", "py-4");
  });
});

describe.each([
  ["IfModal", IfModal],
  ["HbModal", HbModal],
] as const)("%s", (_name, Modal) => {
  function Harness({ closable = true }: { closable?: boolean }) {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>Open</button>
        {open && (
          <Modal title="Create message" width={722} closable={closable} onClose={() => setOpen(false)}
            footer={<><button type="button">Cancel</button><button type="button">OK</button></>}>
            <input aria-label="Name" />
          </Modal>
        )}
      </>
    );
  }

  it("is an aria-modal dialog named by its title, closed by Escape, focus back on the opener", async () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open" });
    await userEvent.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Create message" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("traps Tab inside the box", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    const dialog = screen.getByRole("dialog");
    const focusables = within(dialog).getAllByRole("button").concat(within(dialog).getAllByRole("textbox"));
    for (let i = 0; i < focusables.length + 2; i++) {
      await userEvent.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
    await userEvent.tab({ shift: true });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
  });

  it("closable=false draws no × and ignores Escape", async () => {
    render(<Harness closable={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("the × closes it", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

const ACCOUNTS: AccountMeta[] = [
  { id: "acc1", nickname: "Alice", has_session: true, color: "#f00", is_active: true },
  { id: "acc2", nickname: "Bea", has_session: false, color: "#0f0", is_active: true },
];

describe("IfCreatorSelect + useCreatorParam", () => {
  function Harness({ accounts = ACCOUNTS }: { accounts?: AccountMeta[] }) {
    const [id, setId] = useCreatorParam(accounts);
    return (
      <>
        <IfCreatorSelect accounts={accounts} value={id} onChange={setId} />
        <p data-testid="body">{id ?? "none"}</p>
      </>
    );
  }

  it("falls back to the first account and shows its online dot", () => {
    const { container } = renderWithProviders(<Harness />);
    expect(screen.getByTestId("body")).toHaveTextContent("acc1");
    expect(screen.getByRole("combobox", { name: "Creator" })).toHaveTextContent("Alice");
    expect(container.querySelector("[data-online]")).toBeInTheDocument();
  });

  it("reads ?creator= and ignores an unknown id", () => {
    window.history.replaceState(null, "", "/growth/scripts?creator=acc2");
    const { unmount } = renderWithProviders(<Harness />);
    expect(screen.getByTestId("body")).toHaveTextContent("acc2");
    unmount();
    window.history.replaceState(null, "", "/growth/scripts?creator=nope");
    renderWithProviders(<Harness />);
    expect(screen.getByTestId("body")).toHaveTextContent("acc1");
  });

  it("a pick updates the body and replaces the URL, keeping other params", async () => {
    window.history.replaceState(null, "", "/growth/scripts?tab=x");
    renderWithProviders(<Harness />);
    await userEvent.click(screen.getByRole("combobox", { name: "Creator" }));
    await userEvent.click(screen.getByRole("option", { name: /Bea/ }));
    expect(screen.getByTestId("body")).toHaveTextContent("acc2");
    expect(replace).toHaveBeenCalledWith("/growth/scripts?tab=x&creator=acc2", { scroll: false });
  });

  it("is null with no accounts", () => {
    renderWithProviders(<Harness accounts={[]} />);
    expect(screen.getByTestId("body")).toHaveTextContent("none");
    expect(screen.getByRole("combobox", { name: "Creator" })).toHaveTextContent("No creators");
  });
});
