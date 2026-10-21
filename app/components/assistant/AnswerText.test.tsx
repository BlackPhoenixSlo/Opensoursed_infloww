/**
 * AnswerText — the answer reads as prose, not as markdown source.
 *
 * The bug these cases lock down was visible in the product: an answer arrived
 * as `**Growth → Profile promotion**` and the panel printed the asterisks, so the
 * one thing worth reading — the tab name — was buried in punctuation. The
 * invariant is therefore blunt: no raw `**` ever reaches the DOM, and a tab
 * name is a link the reader can click instead of a route to re-type.
 */
import { describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach } from "vitest";

import { AnswerText } from "./AnswerText";

afterEach(cleanup);

describe("AnswerText", () => {
  it("renders bold as emphasis and never as asterisks", () => {
    const { container } = render(
      <AnswerText text="Go to **Growth → Profile promotion**, set a **Name**." />,
    );
    expect(container.textContent).not.toContain("**");
    expect(screen.getByText("Name").tagName).toBe("STRONG");
  });

  it("links the click path inside bold", () => {
    // Where it points is answerLinks.test.ts's job; here, that it is a link.
    render(<AnswerText text="Go to **Growth → Profile promotion** and press Create." />);
    const link = screen.getByRole("link", { name: "Growth → Profile promotion" });
    // The link sits INSIDE the bold run — bold and linked, not one or other.
    expect(link.closest("strong")).not.toBeNull();
  });

  it("links a half-bolded path as one path", () => {
    // Resolved span by span, the bold "Settings" would link on its own to
    // Your Account; as one path, every piece of it opens one place.
    render(<AnswerText text="Open Growth → **Smart lists** → **Settings**, then Save." />);
    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["Growth → ", "Smart lists"]);
    expect(new Set(links.map((l) => l.getAttribute("href"))).size).toBe(1);
  });

  it("renders bullet and numbered lists as lists", () => {
    const { container } = render(
      <AnswerText
        text={"Steps:\n\n1. Open the tab\n2. Tick Enabled\n\n- one note\n- another"}
      />,
    );
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    expect(container.querySelectorAll("ul li")).toHaveLength(2);
    expect(container.textContent).not.toContain("- one note");
  });

  it("folds a wrapped continuation into the item above it", () => {
    const { container } = render(
      <AnswerText text={"1. Open the tab\n   and then save it\n2. Done"} />,
    );
    const items = container.querySelectorAll("ol li");
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toBe("Open the tab and then save it");
  });

  it("rejoins hard-wrapped prose into one paragraph", () => {
    const { container } = render(
      <AnswerText text={"This sentence was\nwrapped by the model.\n\nSecond."} />,
    );
    const ps = container.querySelectorAll("p");
    expect(ps).toHaveLength(2);
    expect(ps[0].textContent).toBe("This sentence was wrapped by the model.");
  });

  it("renders inline code and does not linkify inside it", () => {
    const { container } = render(
      <AnswerText text="Set `hours_to_live` and see Growth → Profile promotion." />,
    );
    expect(container.querySelector("code")?.textContent).toBe("hours_to_live");
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });

  it("degrades an unclosed bold to a visible asterisk, not a swallowed answer", () => {
    const { container } = render(<AnswerText text="A **stray marker here." />);
    expect(container.textContent).toBe("A **stray marker here.");
  });

  it("never emits raw HTML from the model", () => {
    const { container } = render(
      <AnswerText text={'<img src=x onerror="alert(1)"> and **bold**'} />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x");
  });

  it("mutes the whole answer when the turn carried an error", () => {
    const { container } = render(<AnswerText text="Budget used up." muted />);
    expect(container.firstElementChild?.className).toContain("text-fg-dim");
  });
});
