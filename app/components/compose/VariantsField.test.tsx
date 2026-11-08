/** VariantsField: the one text-variant pool (Trigger editors, PremadeForm, funnel steps); the caller owns the list. */
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { VariantsField } from "@/components/compose/VariantsField";

afterEach(() => cleanup());

function Harness({ initial, max, spy }: { initial: string[]; max?: number; spy: (v: string[]) => void }) {
  const [v, setV] = useState(initial);
  return <VariantsField id="t" label="Message" variants={v} max={max} onChange={(n) => { spy(n); setV(n); }} />;
}
const last = (spy: ReturnType<typeof vi.fn>) => spy.mock.calls[spy.mock.calls.length - 1][0];
const importPasted = (text: string) => {
  fireEvent.click(screen.getByRole("button", { name: "Import captions" }));
  fireEvent.change(screen.getByLabelText("Paste captions"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Add pasted" }));
};

describe("VariantsField", () => {
  it("edits one variant, adds a blank, removes one; never removes the last", () => {
    const spy = vi.fn();
    render(<Harness initial={["a", "b"]} spy={spy} />);
    fireEvent.change(screen.getByLabelText("Message, variant 2"), { target: { value: "z" } });
    expect(last(spy)).toEqual(["a", "z"]);
    fireEvent.click(screen.getByRole("button", { name: "Add variant" }));
    expect(last(spy)).toEqual(["a", "z", ""]);
    fireEvent.click(screen.getByRole("button", { name: "Remove variant 1" }));
    expect(last(spy)).toEqual(["z", ""]);
    fireEvent.click(screen.getByRole("button", { name: "Remove variant 2" }));
    expect(last(spy)).toEqual(["z"]);
    expect(screen.queryByRole("button", { name: /^Remove variant/ })).toBeNull();
  });

  it("import replaces a lone blank variant, else appends, dupes skipped", () => {
    const spy = vi.fn();
    render(<Harness initial={[""]} spy={spy} />);
    importPasted("x\ny");
    expect(last(spy)).toEqual(["x", "y"]);
    importPasted("y\nw");
    expect(last(spy)).toEqual(["x", "y", "w"]);
  });

  it("max caps Add and Import", () => {
    const spy = vi.fn();
    render(<Harness initial={["a"]} max={2} spy={spy} />);
    importPasted("b\nc");
    expect(last(spy)).toEqual(["a", "b"]);
    expect(screen.queryByRole("button", { name: "Add variant" })).toBeNull();
  });
});
