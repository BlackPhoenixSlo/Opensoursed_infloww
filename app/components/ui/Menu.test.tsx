import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { Menu } from "./Menu";

afterEach(cleanup);

describe("Menu", () => {
  it("Escape closes it (the Vault rail's folder ⋯ menu); other keys don't", () => {
    render(<Menu label="⋯" ariaLabel="Folder actions" items={[{ label: "Download folder" }]} />);
    fireEvent.click(screen.getByRole("button", { name: "Folder actions" }));
    expect(screen.getByRole("menu")).toBeTruthy();
    fireEvent.keyDown(document, { key: "a" });
    expect(screen.getByRole("menu")).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
