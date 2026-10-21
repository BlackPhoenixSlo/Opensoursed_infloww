/**
 * NotAppliedYet is field-scoped (docs/spec/phase-04-apply-stored-settings.md ›
 * Notes): it takes the names of the fields still not applied and renders
 * nothing when given none. With no `fields` it is the whole-Panel sentence, as
 * every Panel shows it today (each Panel's own test pins its note).
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { NotAppliedYet } from "@/components/settings/SettingsPanel";

afterEach(cleanup);

describe("NotAppliedYet", () => {
  it("renders nothing when given no field names", () => {
    const { container } = render(<NotAppliedYet fields={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the one field still not applied", () => {
    render(<NotAppliedYet fields={["Language"]} />);
    expect(screen.getByText("Saved for your organization; Language is not applied yet.")).toBeInTheDocument();
  });

  it("names several fields still not applied", () => {
    render(<NotAppliedYet fields={["Agency name", "Language", "AI Translator prompt"]} />);
    expect(screen.getByText(
      "Saved for your organization; Agency name, Language and AI Translator prompt are not applied yet.",
    )).toBeInTheDocument();
  });

  it("with no fields given keeps the whole-Panel sentence", () => {
    render(<NotAppliedYet />);
    expect(screen.getByText("Saved for your organization; not applied yet.")).toBeInTheDocument();
  });
});
