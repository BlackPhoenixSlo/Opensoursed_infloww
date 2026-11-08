import { StrictMode, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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
  EmptyState, HB_TABLE, HbButton, HbFilter, HbModal, HbPager, HbSelect, IF_TABLE, IfBody, IfButton, IfCard, IfHelp,
  IfCreatorSelect, IfInput, IfLearn, IfModal, IfPager, IfRangePicker, IfSegmented, IfSelect, IfSwitch, IfTabs,
  InflowwPageHeader, saveVerdict, useCreatorParam,
} from "./infloww";
import { PageFrame } from "@/components/shell/PageFrame";
import { EditorFooter, useModalFocus } from "@/components/ui/ifModal";

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

  it("art={false} drops the illustration and passes role / aria through", () => {
    const { container } = render(
      <EmptyState art={false} role="group" aria-label="Posts" text="No content yet" action={<button type="button">Compose</button>} />,
    );
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByRole("group", { name: "Posts" })).toHaveAttribute("data-empty-state", "data");
    expect(screen.getByText("No content yet")).not.toHaveClass("mt-2");
  });

  it("a caller's attributes never clobber data-empty-state", () => {
    render(<EmptyState role="group" aria-label="Posts" {...{ "data-empty-state": "x" }} />);
    expect(screen.getByRole("group", { name: "Posts" })).toHaveAttribute("data-empty-state", "data");
  });

  it("help renders between the text and the action", () => {
    render(<EmptyState art={false} text="No content yet" help={<IfHelp id="h">Add one first.</IfHelp>} action={<button type="button">Compose</button>} />);
    const help = screen.getByText("Add one first.");
    expect(help).toHaveClass("text-[12px]", "text-muted");
    expect(help).toHaveAttribute("id", "h");
    expect(screen.getByText("No content yet").compareDocumentPosition(help) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(help.compareDocumentPosition(screen.getByRole("button", { name: "Compose" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
    // A page-foot menu opens upward, inside the viewport.
    expect(screen.getByRole("listbox").parentElement).toHaveClass("bottom-full");
    expect(screen.getByRole("listbox").parentElement).not.toHaveClass("top-full");
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
  function Harness({ closable = true, picker = false }: { closable?: boolean; picker?: boolean }) {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>Open</button>
        {open && (
          <Modal title="Create message" width={722} closable={closable} onClose={() => setOpen(false)}
            footer={<><button type="button">Cancel</button><button type="button">OK</button></>}>
            <input aria-label="Name" />
            {/* A non-modal picker portaled to body, like the composers' emoji / template pickers. */}
            {picker && createPortal(<div><input aria-label="Search emoji" /><button type="button">Smile</button></div>, document.body)}
          </Modal>
        )}
      </>
    );
  }

  it("with no title: named by label, no empty heading", () => {
    render(<Modal label="Preview" onClose={vi.fn()}>body</Modal>);
    expect(screen.getByRole("dialog", { name: "Preview" })).toBeTruthy();
    expect(screen.queryByRole("heading")).toBeNull();
  });

  it("leaves an Escape a control inside already handled (preventDefault) alone", () => {
    const onClose = vi.fn();
    render(
      <Modal title="Create message" onClose={onClose}>
        <input aria-label="Name" onKeyDown={(e) => { if (e.key === "Escape") e.preventDefault(); }} />
      </Modal>,
    );
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Name" }), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

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

  it("the trap skips controls in a disabled fieldset", () => {
    render(
      <Modal title="Edit" closable={false} onClose={() => {}}>
        <input aria-label="First" />
        <fieldset disabled><input aria-label="Locked" /><button type="button">Locked button</button></fieldset>
      </Modal>,
    );
    const first = screen.getByRole("textbox", { name: "First" });
    first.focus();
    // `First` is the box's only focusable: Tab and Shift+Tab stay on it, never on a locked control.
    expect(fireEvent.keyDown(first, { key: "Tab" })).toBe(false);
    expect(first).toHaveFocus();
    expect(fireEvent.keyDown(first, { key: "Tab", shiftKey: true })).toBe(false);
    expect(first).toHaveFocus();
  });

  it.each([["Tab", false], ["Shift+Tab", true]] as const)(
    "focus on the page behind (not a portal above): %s brings it back into the box", (_k, shiftKey) => {
      render(
        <>
          <button type="button">Behind</button>
          <Modal title="Edit" onClose={() => {}}><input aria-label="Name" /></Modal>
        </>,
      );
      const behind = screen.getByRole("button", { name: "Behind" });
      behind.focus();
      expect(fireEvent.keyDown(behind, { key: "Tab", shiftKey })).toBe(false);
      expect(screen.getByRole("dialog")).toContainElement(document.activeElement as HTMLElement);
    });

  it("leaves Tab and Escape to a portaled picker that holds focus", async () => {
    render(<Harness picker />);
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    const dialog = screen.getByRole("dialog");
    const search = screen.getByRole("textbox", { name: "Search emoji" });
    expect(dialog).not.toContainElement(search);
    search.focus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Smile" })).toHaveFocus();
    search.focus();
    expect(fireEvent.keyDown(search, { key: "Tab" })).toBe(true);
    expect(fireEvent.keyDown(search, { key: "Escape" })).toBe(true);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    // Back inside the box the trap holds again.
    within(dialog).getByRole("textbox", { name: "Name" }).focus();
    for (let i = 0; i < 6; i++) {
      await userEvent.tab();
      expect(dialog).toContainElement(document.activeElement as HTMLElement);
    }
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("a modal layer on top (vault picker, lightbox) takes Escape and Tab; once it goes the trap is back", async () => {
    function Layer() {
      const ref = useRef<HTMLDivElement>(null);
      useModalFocus(ref);
      return createPortal(<div ref={ref} tabIndex={-1} role="dialog" aria-label="Layer" />, document.body);
    }
    const onClose = vi.fn();
    function Wrapped() {
      const [layer, setLayer] = useState(false);
      return (
        <>
          <Modal title="Create message" onClose={onClose} footer={<button type="button" onClick={() => setLayer((v) => !v)}>Layer</button>}>
            <input aria-label="Name" />
          </Modal>
          {layer && <Layer />}
        </>
      );
    }
    render(<Wrapped />);
    const dialog = screen.getByRole("dialog");
    const toggle = within(dialog).getByRole("button", { name: "Layer" });
    fireEvent.click(toggle);
    toggle.focus();
    // Last focusable: with a layer on top the lower box does not wrap and Escape is not taken; the layer (its own
    // trap) takes Tab back into itself.
    expect(fireEvent.keyDown(toggle, { key: "Escape" })).toBe(true);
    expect(onClose).not.toHaveBeenCalled();
    expect(fireEvent.keyDown(toggle, { key: "Tab" })).toBe(false);
    expect(screen.getByRole("dialog", { name: "Layer" })).toHaveFocus();
    fireEvent.click(toggle);
    toggle.focus();
    expect(fireEvent.keyDown(toggle, { key: "Tab" })).toBe(false);
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it.each([["plain", false], ["StrictMode", true]] as const)(
    "nested modals mounted together (%s): Escape is the inner's; once it goes, the outer's", (_m, strict) => {
      const outer = vi.fn();
      const inner = vi.fn();
      function Nested() {
        const [showInner, setShowInner] = useState(true);
        return (
          <Modal title="Outer" onClose={outer} footer={<button type="button" onClick={() => setShowInner(false)}>Drop inner</button>}>
            {showInner && <Modal title="Inner" onClose={inner}><input aria-label="Inner field" /></Modal>}
          </Modal>
        );
      }
      render(strict ? <StrictMode><Nested /></StrictMode> : <Nested />);
      fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Escape" });
      expect(inner).toHaveBeenCalledTimes(1);
      expect(outer).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: "Drop inner" }));
      expect(screen.getByRole("dialog", { name: "Outer" })).toContainElement(document.activeElement as HTMLElement);
      fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Escape" });
      expect(outer).toHaveBeenCalledTimes(1);
      expect(inner).toHaveBeenCalledTimes(1);
    });

  it("one Escape on the top modal closes only it: a window listener (Find, Fan insights) and the lower modal never hear it", () => {
    const lower = vi.fn();
    const upper = vi.fn();
    const onWindow = vi.fn();
    window.addEventListener("keydown", onWindow);
    try {
      render(
        <Modal title="Lower" onClose={lower}>
          <Modal title="Upper" onClose={upper}><input aria-label="Upper field" /></Modal>
        </Modal>,
      );
      fireEvent.keyDown(screen.getByRole("textbox", { name: "Upper field" }), { key: "Escape" });
      expect(upper).toHaveBeenCalledTimes(1);
      expect(lower).not.toHaveBeenCalled();
      expect(onWindow).not.toHaveBeenCalled();
      // A key the modal does not take still reaches the window.
      fireEvent.keyDown(screen.getByRole("textbox", { name: "Upper field" }), { key: "a" });
      expect(onWindow).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener("keydown", onWindow);
    }
  });

  it.each([["plain", false], ["StrictMode", true]] as const)(
    "opened from outside, outer + inner together (%s): the inner going puts focus in the outer, its keys work", (_m, strict) => {
      const outer = vi.fn();
      function Page() {
        const [open, setOpen] = useState(false);
        const [inner, setInner] = useState(true);
        return (
          <>
            <button type="button" onClick={() => setOpen(true)}>Open both</button>
            <button type="button" onClick={() => setInner(false)}>Drop inner</button>
            {open && (
              <Modal title="Outer" onClose={outer} footer={<button type="button">Outer last</button>}>
                <input aria-label="Outer field" />
                {inner && <Modal title="Inner" onClose={() => setInner(false)}><input aria-label="Inner field" /></Modal>}
              </Modal>
            )}
          </>
        );
      }
      render(strict ? <StrictMode><Page /></StrictMode> : <Page />);
      const openBoth = screen.getByRole("button", { name: "Open both" });
      openBoth.focus();
      fireEvent.click(openBoth);
      // A background update drops the inner (fireEvent's click moves no focus).
      fireEvent.click(screen.getByRole("button", { name: "Drop inner" }));
      const box = screen.getByRole("dialog", { name: "Outer" });
      expect(box).toContainElement(document.activeElement as HTMLElement);
      const last = within(box).getByRole("button", { name: "Outer last" });
      last.focus();
      expect(fireEvent.keyDown(last, { key: "Tab" })).toBe(false);
      expect(box).toContainElement(document.activeElement as HTMLElement);
      expect(last).not.toHaveFocus();
      fireEvent.keyDown(document.activeElement as HTMLElement, { key: "Escape" });
      expect(outer).toHaveBeenCalledTimes(1);
    });

  it("a lower modal unmounting under an upper one leaves focus and Escape with the upper", async () => {
    const upperClose = vi.fn();
    function Two() {
      const [lower, setLower] = useState(false);
      const [upper, setUpper] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setLower(true)}>Open lower</button>
          <button type="button" onClick={() => setLower(false)}>Drop lower</button>
          {lower && (
            <Modal title="Lower" onClose={() => setLower(false)}
              footer={<button type="button" onClick={() => setUpper(true)}>Open upper</button>}>
              <input aria-label="Lower field" />
            </Modal>
          )}
          {upper && <Modal title="Upper" onClose={upperClose}><input aria-label="Upper field" /></Modal>}
        </>
      );
    }
    render(<Two />);
    const opener = screen.getByRole("button", { name: "Open lower" });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(screen.getByRole("button", { name: "Open upper" }));
    const upper = screen.getByRole("dialog", { name: "Upper" });
    const field = within(upper).getByRole("textbox", { name: "Upper field" });
    field.focus();
    // A background update drops the lower modal (fireEvent's click moves no focus).
    fireEvent.click(screen.getByRole("button", { name: "Drop lower" }));
    expect(screen.queryByRole("dialog", { name: "Lower" })).not.toBeInTheDocument();
    expect(field).toHaveFocus();
    fireEvent.keyDown(field, { key: "Escape" });
    expect(upperClose).toHaveBeenCalledTimes(1);
  });

  it("a lower modal unmounting while focus sat in it moves focus into the upper, not to its opener", () => {
    function Two() {
      const [lower, setLower] = useState(false);
      const [upper, setUpper] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setLower(true)}>Open lower</button>
          {lower && (
            <Modal title="Lower" onClose={() => setLower(false)}
              footer={<><button type="button" onClick={() => setUpper(true)}>Open upper</button>
                <button type="button" onClick={() => setLower(false)}>Drop me</button></>}>
              <input aria-label="Lower field" />
            </Modal>
          )}
          {upper && <Modal title="Upper" onClose={() => setUpper(false)}><input aria-label="Upper field" /></Modal>}
        </>
      );
    }
    render(<Two />);
    const opener = screen.getByRole("button", { name: "Open lower" });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(screen.getByRole("button", { name: "Open upper" }));
    const drop = screen.getByRole("button", { name: "Drop me" });
    drop.focus();
    fireEvent.click(drop);
    expect(opener).not.toHaveFocus();
    expect(screen.getByRole("dialog", { name: "Upper" })).toContainElement(document.activeElement as HTMLElement);
  });

  it.each([["plain", false], ["StrictMode", true]] as const)(
    "a dialog that closes as it opens the next (%s): closing the next puts focus back on the first one's opener", async (_m, strict) => {
      function Chain() {
        const [step, setStep] = useState<0 | 1 | 2>(0);
        return (
          <>
            <button type="button" onClick={() => setStep(1)}>New message</button>
            {step === 1 && (
              <Modal title="Pick" onClose={() => setStep(0)}
                footer={<button type="button" onClick={() => setStep(2)}>Next</button>}>
                <input aria-label="Pick field" />
              </Modal>
            )}
            {step === 2 && <Modal title="Compose" onClose={() => setStep(0)}><input aria-label="Text" /></Modal>}
          </>
        );
      }
      render(strict ? <StrictMode><Chain /></StrictMode> : <Chain />);
      const opener = screen.getByRole("button", { name: "New message" });
      await userEvent.click(opener);
      await userEvent.click(screen.getByRole("button", { name: "Next" }));
      expect(screen.getByRole("dialog", { name: "Compose" })).toContainElement(document.activeElement as HTMLElement);
      await userEvent.keyboard("{Escape}");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(opener).toHaveFocus();
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
  { id: "acc1", nickname: "Alice", has_session: true, color: "#f00", is_active: true, proxy_down: false },
  { id: "acc2", nickname: "Bea", has_session: false, color: "#0f0", is_active: true, proxy_down: false },
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

describe("IfModal footerSlot", () => {
  it("an editor's EditorFooter lands in an IfModal footerSlot's footer, after the caller's Cancel; a submit there still submits", () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    function Editor() {
      return (
        <form id="ed-form" onSubmit={onSubmit}>
          <input aria-label="Name" />
          <EditorFooter><button type="submit" form="ed-form">Save</button></EditorFooter>
        </form>
      );
    }
    render(<IfModal title="Edit" onClose={() => {}} footer={<button type="button">Cancel</button>} footerSlot><Editor /></IfModal>);
    const save = screen.getByRole("button", { name: "Save" });
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel.parentElement).toContainElement(save);
    expect(cancel.compareDocumentPosition(save) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Name" }).closest("form")).not.toContainElement(save);
    fireEvent.click(save);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    cleanup();
    // Alone (no slot provided) the buttons sit inline under the body.
    render(<Editor />);
    expect(screen.getByRole("textbox", { name: "Name" }).closest("form")).toContainElement(screen.getByRole("button", { name: "Save" }));
  });
  it("a modal without footerSlot inside one with it keeps its own editor's buttons inline", () => {
    render(
      <IfModal title="Outer" onClose={() => {}} footerSlot>
        <IfModal title="Inner" onClose={() => {}}>
          <div data-testid="inner-body"><EditorFooter><button type="button">Done</button></EditorFooter></div>
        </IfModal>
      </IfModal>,
    );
    expect(screen.getByTestId("inner-body")).toContainElement(screen.getByRole("button", { name: "Done" }));
  });
});

describe("saveVerdict: a save mutation's SaveRow verdict", () => {
  const M = (o: Partial<{ isPending: boolean; isSuccess: boolean; error: Error | null }>) =>
    ({ isPending: false, isSuccess: false, error: null, ...o });
  it.each([
    ["idle", M({}), true, { pending: false, saved: false, error: null }],
    ["running", M({ isPending: true }), true, { pending: true, saved: false, error: null }],
    ["landed", M({ isSuccess: true }), true, { pending: false, saved: true, error: null }],
    ["landed, edited since", M({ isSuccess: true }), false, { pending: false, saved: false, error: null }],
    ["failed", M({ error: new Error("refused") }), true, { pending: false, saved: false, error: "refused" }],
    ["failed, no message", M({ error: new Error("") }), true, { pending: false, saved: false, error: "Save failed" }],
  ])("%s", (_n, m, clean, want) => {
    expect(saveVerdict(m, clean)).toEqual(want);
  });
});
