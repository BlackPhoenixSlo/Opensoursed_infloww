import { describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

vi.mock("@/lib/plugins.generated.register", () => ({ PLUGINS: [] }));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
  redirect: (to: string) => {
    throw new Error(`NEXT_REDIRECT ${to}`);
  },
}));
vi.mock("@/components/fansly-manager/FanslyManagerPage", () => ({ FanslyManagerPage: () => null }));
vi.mock("@/components/fansly-manager/FanslyMirrorFrame", () => ({ FanslyMirrorFrame: () => null }));
vi.mock("@/lib/fansly-mirror-route", async (importOriginal) => {
  const real = await importOriginal<typeof import("@/lib/fansly-mirror-route")>();
  const table = {
    home: { index: "", pages: { "": "Home" } },
    lists: { index: "", pages: { "": "Lists", list: "List" } },
  };
  return { ...real, fanslyRouteOf: (section: string, path: readonly string[], creator: string | null) => real.fanslyRouteOf(section, path, creator, table) };
});

import { FanslyManagerPage } from "@/components/fansly-manager/FanslyManagerPage";
import { FanslyMirrorFrame } from "@/components/fansly-manager/FanslyMirrorFrame";
import Page, { generateMetadata } from "./page";

const props = (section: string, path?: string[], creator?: string) => ({
  params: Promise.resolve({ section, path }),
  searchParams: Promise.resolve(creator ? { creator } : {}),
});
const open = (section: string, path?: string[], creator?: string) => Page(props(section, path, creator));

describe("/fansly-manager/[section]/[[...path]]", () => {
  it.each([
    ["scheduled", "Scheduled Posts"],
    ["lists", "Lists"],
    ["notifications", "Notifications"],
    ["earning-statistics", "Earning Statistics"],
  ])("the bare %s renders its Built page", async (section, label) => {
    const el = (await open(section)) as ReactElement<{ link: { href: string; label: string; flag?: string } }>;
    expect(el.type).toBe(FanslyManagerPage);
    expect(el.props.link).toEqual({ href: `/fansly-manager/${section}`, label, flag: "fansly_manager" });
  });

  it("a mirror path renders the frame on its page, titled '<nav label>: <page title>'", async () => {
    const el = (await open("lists", ["list"], "B")) as ReactElement<{ src: string; title: string }>;
    expect(el.type).toBe(FanslyMirrorFrame);
    expect(el.props).toEqual({ src: "/fansly-mirror/pages/lists/list.html", title: "Lists: List" });
    expect((await open("home")) as ReactElement).toMatchObject({ props: { src: "/fansly-mirror/pages/home/index.html" } });
    expect(await generateMetadata(props("home"))).toEqual({ title: "Homepage: Home" });
  });

  it("the mirror's earnings link redirects to Built Earning Statistics, keeping ?creator=", async () => {
    await expect(open("statistics", ["earnings"], "B")).rejects.toThrow("NEXT_REDIRECT /fansly-manager/earning-statistics?creator=B");
    await expect(open("statistics", ["earnings"])).rejects.toThrow(/^NEXT_REDIRECT \/fansly-manager\/earning-statistics$/);
  });

  it.each([
    ["nope", undefined],
    ["home", ["nope"]],
    ["earning-statistics", ["x"]],
    ["__proto__", undefined],
  ])("answers 404 for %s %s", async (section, path) => {
    await expect(open(section, path)).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
