import { describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));
vi.mock("@/components/fansly-manager/FanslyManagerPage", () => ({ FanslyManagerPage: () => null }));

import Page from "./page";

const open = (page: string) => Page({ params: Promise.resolve({ page }) });

describe("/fansly-manager/[page]", () => {
  it.each(["scheduled", "lists", "notifications", "earning-statistics"])("renders built page %s", async (page) => {
    const el = (await open(page)) as ReactElement<{ link: { href: string; flag?: string } }>;
    expect(el.props.link).toMatchObject({ href: `/fansly-manager/${page}`, flag: "fansly_manager" });
  });

  it.each(["home", "profile", "settings", "messages", "nope"])("answers 404 for %s", async (page) => {
    await expect(open(page)).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
