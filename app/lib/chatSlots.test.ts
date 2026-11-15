/** The nav's plugin slots (lib/chatSlots.ts) with a made-up plugin. */
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/plugins.generated.register", () => ({
  PLUGINS: [
    {
      navLinks: [
        { group: "My Automations", first: true, link: { label: "Plugin first", href: "/growth/plugin-first" } },
        { group: "My Automations", link: { label: "Plugin last", href: "/growth/plugin-last" } },
        { group: "No such group", link: { label: "Lost", href: "/lost" } },
      ],
      popoutModeRoutes: ["/messages-pro/mode"],
    },
  ],
}));

import { CHATTER_OPT_IN_PAGES, SIDEBAR, findNavLink, isGroup, openPopout } from "@/lib/nav";

describe("plugin slots", () => {
  it("navLinks join their group, first or last; a link for no group goes nowhere", () => {
    const g = SIDEBAR.find((n) => isGroup(n) && n.label === "My Automations");
    const hrefs = g && isGroup(g) ? g.children.map((c) => c.href) : [];
    expect(hrefs[0]).toBe("/growth/plugin-first");
    expect(hrefs.at(-1)).toBe("/growth/plugin-last");
    expect(hrefs).toHaveLength(7);
    expect(CHATTER_OPT_IN_PAGES.has("/growth/plugin-first")).toBe(true);
    expect(findNavLink("/lost")).toBeUndefined();
  });

  it("popoutModeRoutes: the plain Messages Pro link takes the window from a mode route to the inbox", () => {
    for (const [path, to] of [["/messages-pro/mode", "/messages-pro"], ["/messages-pro/acc1/123", "/messages-pro/acc1/123"]]) {
      const win = { location: { pathname: path, search: "", href: path }, focus: vi.fn() };
      const open = vi.spyOn(window, "open").mockReturnValue(win as unknown as Window);
      openPopout("/messages-pro");
      expect(win.location.href).toBe(to);
      open.mockRestore();
    }
  });
});
