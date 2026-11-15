/**
 * Full AI Chat's Fans dialog: the top "Fans & Following" row only reads the pick. Include while no list is included,
 * Neither once one is; picking Include there clears the includes (excludes stay). Save never stores the row.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

vi.mock("@/components/audience/fanLists", () => ({
  useFanLists: () => ({ isLoading: false, data: {}, customLists: [{ id: 11, name: "VIP", usersCount: 4 }, { id: 12, name: "Timewasters" }] }),
}));

import { FansRow } from "@/components/automations/FullAiFans";
import type { FullAiConfig } from "@/components/automations/fullAiConfig";
import type { FullAiConfigApi } from "@/hooks/useFullAiConfig";

afterEach(cleanup);

const open = (fans: { include: number[]; exclude: number[] }) => {
  const edit = vi.fn();
  render(<FansRow accountId="1" draft={{ fans } as FullAiConfig} off={false} cfg={{ edit } as unknown as FullAiConfigApi} />);
  fireEvent.click(screen.getByRole("button", { name: "Choose fans" }));
  const radio = (group: string, name: string) => within(screen.getByRole("radiogroup", { name: group })).getByRole("radio", { name });
  const on = (group: string, name: string) => radio(group, name).getAttribute("aria-checked") === "true";
  return { edit, radio, on };
};

describe("Fans dialog · Fans & Following row", () => {
  it("has two options and reads Include while no list is included", () => {
    const { on } = open({ include: [], exclude: [] });
    expect(within(screen.getByRole("radiogroup", { name: "Fans & Following" })).getAllByRole("radio")).toHaveLength(2);
    expect(on("Fans & Following", "Include")).toBe(true);
  });

  it("swaps to Neither when a list is included, back to Include when it returns to Neither", () => {
    const { radio, on } = open({ include: [], exclude: [] });
    fireEvent.click(radio("VIP", "Include"));
    expect(on("Fans & Following", "Neither")).toBe(true);
    fireEvent.click(radio("VIP", "Neither"));
    expect(on("Fans & Following", "Include")).toBe(true);
  });

  it("an excluded list leaves it on Include", () => {
    const { radio, on } = open({ include: [], exclude: [] });
    fireEvent.click(radio("Timewasters", "Exclude"));
    expect(on("Fans & Following", "Include")).toBe(true);
  });

  it("picking Include clears the included lists, keeps excludes, and Save stores lists only", () => {
    const { edit, radio, on } = open({ include: [11], exclude: [12] });
    expect(on("Fans & Following", "Neither")).toBe(true);
    fireEvent.click(radio("Fans & Following", "Include"));
    expect(on("VIP", "Neither")).toBe(true);
    expect(on("Timewasters", "Exclude")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(edit).toHaveBeenCalledWith({ fans: { include: [], exclude: [12] } });
  });
});
