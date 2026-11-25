export interface UndoOptions {
  attrMode: "single" | "all-in-order";
  classUndo: "snapshot" | "toggle";
  skipEqualText: boolean;
}

export function undoList({ attrMode, classUndo, skipEqualText }: UndoOptions) {
  const undos = new WeakMap<Document, (() => void)[]>();
  let sink: (() => void)[] | null = null;

  function track(doc: Document, undo: () => void) {
    if (sink) return void sink.push(undo);
    let u = undos.get(doc);
    if (!u) undos.set(doc, (u = []));
    u.push(undo);
  }
  function restore(doc: Document): void {
    const u = undos.get(doc) ?? [];
    while (u.length) u.pop()!();
  }
  function own(apply: () => void): () => void {
    const mine: (() => void)[] = [];
    const was = sink;
    sink = mine;
    try {
      apply();
    } finally {
      sink = was;
    }
    return () => {
      while (mine.length) mine.pop()!();
    };
  }
  function setText(doc: Document, el: Element | null | undefined, text: string) {
    if (!el) return;
    const was = el.textContent ?? "";
    if (skipEqualText && was === text) return;
    track(doc, () => (el.textContent = was));
    el.textContent = text;
  }
  function setClass(doc: Document, el: Element, cls: string, on: boolean) {
    if (el.classList.contains(cls) === on) return;
    if (classUndo === "toggle") track(doc, () => el.classList.toggle(cls, !on));
    else {
      const was = el.getAttribute("class");
      track(doc, () => (was === null ? el.removeAttribute("class") : el.setAttribute("class", was)));
    }
    el.classList.toggle(cls, on);
  }
  function setAttr(doc: Document, el: Element | null | undefined, name: string, value: string | null) {
    if (!el) return;
    const was = el.getAttribute(name);
    if (was === value) return;
    if (attrMode === "single") track(doc, () => (was === null ? el.removeAttribute(name) : el.setAttribute(name, was)));
    else {
      const all = [...el.attributes].map((a) => [a.name, a.value] as const);
      track(doc, () => {
        for (const a of [...el.attributes]) el.removeAttribute(a.name);
        for (const [n, v] of all) el.setAttribute(n, v);
      });
    }
    if (value === null) el.removeAttribute(name);
    else el.setAttribute(name, value);
  }
  function swapIn(doc: Document, el: Element | null | undefined, pattern: RegExp, to: string) {
    if (!el) return;
    const walker = doc.createTreeWalker(el, 4 );
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const was = n.nodeValue ?? "";
      if (!pattern.test(was)) continue;
      const node = n;
      track(doc, () => (node.nodeValue = was));
      node.nodeValue = was.replace(pattern, to);
      return;
    }
  }
  return { track, restore, own, setText, setClass, setAttr, swapIn };
}
