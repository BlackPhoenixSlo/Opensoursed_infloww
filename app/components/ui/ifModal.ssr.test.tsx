// @vitest-environment node
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import { HbModal, IfModal } from "@/components/ui/ifModal";

describe("modals on the server", () => {
  it("has no DOM", () => {
    expect(typeof document).toBe("undefined");
    expect(typeof HTMLElement).toBe("undefined");
  });
  it.each([["IfModal", IfModal], ["HbModal", HbModal]] as const)("a page with an open %s renders to a string", (_n, Modal) => {
    const html = renderToString(<main><Modal title="Create message" onClose={() => {}}><input aria-label="Name" /></Modal></main>);
    expect(html).toContain("Create message");
  });
});
