/** RawJsonModal's Escape: closes an untyped buffer (whatever the caller seeded), never a typed one or mid-save. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { RawJsonModal } from "@/components/automations/RawJsonModal";

afterEach(() => cleanup());

const escape = () => fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
function open(props: { text?: string; busy?: boolean } = {}) {
  const onClose = vi.fn();
  const view = render(
    <RawJsonModal name="n" text={props.text ?? "{}"} onText={() => {}} busy={props.busy}
      onReformat={() => {}} onSave={() => {}} onClose={onClose} />,
  );
  return { onClose, view };
}

describe("RawJsonModal Escape", () => {
  it("untyped, the caller's seed landing late included: Escape closes", () => {
    const { onClose, view } = open({ text: "" });
    view.rerender(<RawJsonModal name="n" text={'{"a":1}'} onText={() => {}}
      onReformat={() => {}} onSave={() => {}} onClose={onClose} />);
    escape();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
  it("typed: Escape does nothing; × closes", () => {
    const { onClose } = open();
    fireEvent.change(screen.getByRole("textbox", { name: "Raw JSON" }), { target: { value: "{ }" } });
    escape();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
  it("mid-save: Escape does nothing", () => {
    const { onClose } = open({ busy: true });
    escape();
    expect(onClose).not.toHaveBeenCalled();
  });
});
