import { cssNormalize, cssTokens } from "./css.mjs";

const ICON_FAMILIES = [{ family: /^font ?awesome\b/i, selectors: [".fa", '[class^="fa-"]', '[class*=" fa-"]'] }];

const ruleOf = (family) => ICON_FAMILIES.find((r) => r.family.test(family));

export function fontFaces(raw) {
  const toks = cssTokens(cssNormalize(raw)).tokens.filter((t) => t.type !== "ws" && t.type !== "comment");
  const faces = [];
  for (let i = 0; i < toks.length; i++) {
    if (toks[i].type !== "at" || toks[i].value.toLowerCase() !== "font-face" || toks[i + 1]?.type !== "{") continue;
    const face = { family: "", local: false, urls: [] };
    let prop = "";
    for (i += 2; i < toks.length && toks[i].type !== "}"; i++) {
      const t = toks[i];
      if (!prop && t.type === "ident" && toks[i + 1]?.type === ":") prop = toks[i++].value.toLowerCase();
      else if (t.type === ";") prop = "";
      else if (prop === "font-family" && (t.type === "string" || t.type === "ident")) face.family = face.family ? `${face.family} ${t.value}` : t.value;
      else if (prop === "src" && t.type === "url") face.urls.push(t.value);
      else if (prop === "src" && t.type === "function" && t.value.toLowerCase() === "local") face.local = true;
      else if (prop === "src" && t.type === "function" && t.value.toLowerCase() === "url" && toks[i + 1]?.type === "string") face.urls.push(toks[++i].value);
    }
    faces.push(face);
  }
  return faces;
}

export function iconHides(faces) {
  const families = new Map();
  for (const { family, local, key, urls, missing } of faces) {
    const f = families.get(family.toLowerCase()) ?? { family, missing: new Set(), kept: false };
    if (!local && urls > 0 && missing === urls) f.missing.add(key);
    else f.kept = true;
    families.set(family.toLowerCase(), f);
  }
  const hidden = [...families.values()].filter((f) => !f.kept && ruleOf(f.family));
  const selectors = [...new Set(hidden.flatMap((f) => ruleOf(f.family).selectors))].flatMap((s) => [`${s}::before`, `${s}::after`]);
  return {
    lines: hidden.map((f) => `icon glyphs hidden: ${f.family} (${f.missing.size} faces missing)`),
    inject: (doc) => {
      if (!selectors.length) return;
      const style = doc.createElement("style");
      style.textContent = `${selectors.join(",")}{color:transparent!important}`;
      doc.head.append(style);
    },
  };
}
