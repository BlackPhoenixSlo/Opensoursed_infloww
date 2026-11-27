export const codePoint = (n) => (n > 0 && n <= 0x10ffff ? String.fromCodePoint(n) : "�");
const CSS_WS = /[ \t\n]/;
const HEX = /[0-9a-f]/i;
const nameStart = (c) => c !== undefined && (/[a-z_]/i.test(c) || c.charCodeAt(0) >= 0x80);
const nameChar = (c) => nameStart(c) || (c !== undefined && /[0-9-]/.test(c));
export const cssNormalize = (v) => v.replace(/\r\n?|\f/g, "\n").replace(/\0/g, "�");

export function cssTokens(s) {
  const tokens = [];
  let i = 0;
  let bad = false;
  const isEsc = (j) => s[j] === "\\" && s[j + 1] !== "\n";
  const identAt = (j) => (s[j] === "-" ? nameStart(s[j + 1]) || s[j + 1] === "-" || isEsc(j + 1) : nameStart(s[j]) || isEsc(j));
  const NUMBER = /[+-]?(?:\d*\.\d+|\d+)(?:e[+-]?\d+)?/iy;
  const escape = () => {
    if (i >= s.length) {
      bad = true;
      return "�";
    }
    if (HEX.test(s[i])) {
      let h = "";
      while (h.length < 6 && HEX.test(s[i] ?? "")) h += s[i++];
      if (CSS_WS.test(s[i] ?? "")) i++;
      const n = parseInt(h, 16);
      return n === 0 || (n >= 0xd800 && n <= 0xdfff) ? "�" : codePoint(n);
    }
    const c = String.fromCodePoint(s.codePointAt(i));
    i += c.length;
    return c;
  };
  const name = () => {
    let v = "";
    for (;;) {
      if (nameChar(s[i])) v += s[i++];
      else if (isEsc(i)) {
        i++;
        v += escape();
      } else return v;
    }
  };
  while (i < s.length) {
    const start = i;
    const c = s[i];
    const push = (type, value = "") => tokens.push({ type, value, start, end: i });
    if (c === "/" && s[i + 1] === "*") {
      const e = s.indexOf("*/", i + 2);
      bad ||= e < 0;
      i = e < 0 ? s.length : e + 2;
      push("comment");
    } else if (CSS_WS.test(c)) {
      while (CSS_WS.test(s[i] ?? "")) i++;
      push("ws");
    } else if (c === '"' || c === "'") {
      let v = "";
      for (i++; ; ) {
        const d = s[i];
        if (d === c) {
          i++;
          break;
        }
        if (d === undefined || d === "\n") {
          bad = true;
          break;
        }
        if (d === "\\" && s[i + 1] === "\n") i += 2;
        else if (d === "\\") {
          i++;
          v += escape();
        } else v += s[i++];
      }
      push("string", v);
    } else if (((NUMBER.lastIndex = i), NUMBER.test(s))) {
      const num = s.slice(i, NUMBER.lastIndex);
      i = NUMBER.lastIndex;
      if (identAt(i)) push("dimension", num + name());
      else if (s[i] === "%") {
        i++;
        push("dimension", `${num}%`);
      } else push("number", num);
    } else if (identAt(i)) {
      const v = name();
      if (s[i] !== "(") push("ident", v);
      else if (v.toLowerCase() !== "url" || /^[ \t\n]*["']/.test(s.slice(i + 1))) {
        i++;
        push("function", v);
      } else {
        i++;
        let v2 = "";
        while (CSS_WS.test(s[i] ?? "")) i++;
        for (;;) {
          const d = s[i];
          if (d === ")") {
            i++;
            break;
          }
          if (d === undefined || /["'(\x00-\x08\x0b\x0e-\x1f\x7f]/.test(d) || (CSS_WS.test(d) && !/^[ \t\n]*\)/.test(s.slice(i))) || (d === "\\" && !isEsc(i))) {
            bad = true;
            const close = s.indexOf(")", i);
            i = close < 0 ? s.length : close + 1;
            break;
          }
          if (CSS_WS.test(d)) i++;
          else if (d === "\\") {
            i++;
            v2 += escape();
          } else v2 += s[i++];
        }
        push("url", v2);
      }
    } else if (c === "@" && identAt(i + 1)) {
      i++;
      push("at", name());
    } else if (c === "#" && (nameChar(s[i + 1]) || isEsc(i + 1))) {
      i++;
      push("hash", name());
    } else {
      bad ||= c === "\\";
      i++;
      push("(){}[];:,".includes(c) ? c : "delim", c);
    }
  }
  return { tokens, bad };
}

export const HOVER_CLASSES = ["hover-zone"];

const compound = (t, at, side) => t && t[side] === at && t.type !== "ws" && t.type !== "comment" && t.type !== "," && !(t.type === "delim" && ">+~".includes(t.value));

export function hoverRules(css) {
  const { tokens } = cssTokens(css);
  const adds = [];
  const open = [];
  let from = 0;
  tokens.forEach((t, k) => {
    if (t.type === "{") {
      open.push({ from, k });
      from = k + 1;
    } else if (t.type === ";") from = k + 1;
    else if (t.type === "}") {
      const r = open.pop();
      from = k + 1;
      const prelude = r ? tokens.slice(r.from, r.k) : [];
      if (prelude.find((p) => p.type !== "ws" && p.type !== "comment")?.type === "at") return;
      const hits = prelude.filter((p, j) => p.type === "delim" && p.value === "." && prelude[j + 1]?.type === "ident" && prelude[j + 1].start === p.end && HOVER_CLASSES.includes(prelude[j + 1].value) && (compound(prelude[j - 1], p.start, "end") || compound(prelude[j + 2], prelude[j + 1].end, "start")));
      if (!hits.length) return;
      const at = prelude[0].start;
      let rule = css.slice(at, t.end);
      for (const h of hits.reverse()) rule = rule.slice(0, h.start - at) + ":hover" + rule.slice(prelude[prelude.indexOf(h) + 1].end - at);
      adds.push([t.end, rule]);
    }
  });
  let out = "";
  let at = 0;
  for (const [pos, rule] of adds.sort((a, b) => a[0] - b[0])) {
    out += css.slice(at, pos) + rule;
    at = pos;
  }
  return out + css.slice(at);
}
