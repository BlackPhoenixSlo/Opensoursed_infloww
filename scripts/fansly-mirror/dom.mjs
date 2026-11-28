import { createRequire } from "node:module";

const require = createRequire(new URL("../../app/package.json", import.meta.url));
let jsdom;
let decoder;

export function parse(raw, opts = {}) {
  jsdom ??= require("jsdom");
  const { JSDOM, VirtualConsole } = jsdom;
  return new JSDOM(raw, { virtualConsole: new VirtualConsole(), ...opts });
}

export function decodedViews(value) {
  const decode = (v) => {
    const url = v.replace(/(?:%[\da-f]{2})+/gi, (run) => {
      try {
        return decodeURIComponent(run);
      } catch {
        return run.replace(/%([0-7][\da-f])/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
      }
    });
    if (!/&(?:#|[a-z])/i.test(url)) return url;
    decoder ??= parse("").window.document.createElement("textarea");
    decoder.innerHTML = url.replaceAll("<", "&lt;");
    return decoder.textContent;
  };
  const once = decode(value);
  return [...new Set([value, once, decode(once)])];
}
