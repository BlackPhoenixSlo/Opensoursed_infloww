import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Field, NumInput } from "./fields";

describe("shared fields", () => {
  it("keeps a numeric draft clearable and retypable before blur", () => {
    const onChange = vi.fn();
    const { rerender } = render(<Field label="Hours"><NumInput value={1} min={1} onChange={onChange} /></Field>);
    const input = screen.getByRole("spinbutton", { name: "Hours" });
    fireEvent.change(input, { target: { value: "" } });
    expect(input).toHaveValue(null);
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "4" } });
    rerender(<Field label="Hours"><NumInput value={4} min={1} onChange={onChange} /></Field>);
    expect(input).toHaveValue(4);
    expect(onChange).toHaveBeenCalledWith(4);
    fireEvent.blur(input);
    expect(input).toHaveValue(4);
  });

  it("shows a new controlled value when it replaces a held numeric draft", () => {
    const onChange = vi.fn();
    const { rerender } = render(<NumInput aria-label="Hours" value={1} onChange={onChange} />);
    const input = screen.getByRole("spinbutton", { name: "Hours" });
    fireEvent.change(input, { target: { value: "4" } });
    rerender(<NumInput aria-label="Hours" value={4} onChange={onChange} />);
    expect(input).toHaveValue(4);
    rerender(<NumInput aria-label="Hours" value={9} onChange={onChange} />);
    expect(input).toHaveValue(9);
  });

  it("shows a new controlled value after the box was cleared", () => {
    const onChange = vi.fn();
    const { rerender } = render(<NumInput aria-label="Hours" value={1} onChange={onChange} />);
    const input = screen.getByRole("spinbutton", { name: "Hours" });
    fireEvent.change(input, { target: { value: "" } });
    expect(input).toHaveValue(null);
    expect(onChange).not.toHaveBeenCalled();
    rerender(<NumInput aria-label="Hours" value={9} onChange={onChange} />);
    expect(input).toHaveValue(9);
  });

  it("keeps a leading-zero draft until blur", () => {
    const onChange = vi.fn();
    const { rerender } = render(<NumInput aria-label="Hours" value={0} onChange={onChange} />);
    const input = screen.getByRole("spinbutton", { name: "Hours" });
    fireEvent.change(input, { target: { value: "04" } });
    rerender(<NumInput aria-label="Hours" value={4} onChange={onChange} />);
    expect(input).toHaveDisplayValue("04");
    expect(onChange).toHaveBeenCalledWith(4);
    fireEvent.blur(input);
    expect(input).toHaveDisplayValue("4");
  });
});
