import { type DlItem } from "@/components/vault/vaultDownloadReducer";

export const MIN_LEFT_MS = 10 * 60 * 1000;
export const DRM_TEXT = "no link (DRM)";

export interface LinksOpts {
  origin: string;
  accountId: string;
  creator: string;
  label: string;
  direct: boolean;
  now: number;
  token?: string | null;
}

export type LinkKind = "cdn" | "app" | "drm";
export interface LinkRow { id: number; name: string; kind: string; folder: string; link: LinkKind; href: string; app: string }

export interface LinksFile {
  txtName: string;
  htmlName: string;
  txt: string;
  html: string;
  validUntil: number | null;
  rows: LinkRow[];
}

export function urlExpiry(url: string): number | null {
  let q: URLSearchParams;
  try {
    q = new URL(url).searchParams;
  } catch {
    return null;
  }
  const canned = Number(q.get("Expires"));
  if (canned > 0) return canned * 1000;
  const p = q.get("Policy");
  if (!p) return null;
  try {
    const b64 = p.replace(/-/g, "+").replace(/_/g, "=").replace(/~/g, "/");
    const pol = JSON.parse(atob(b64)) as { Statement?: { Condition?: { DateLessThan?: { "AWS:EpochTime"?: number } } }[] };
    const e = Number(pol.Statement?.[0]?.Condition?.DateLessThan?.["AWS:EpochTime"]);
    return e > 0 ? e * 1000 : null;
  } catch {
    return null;
  }
}

export function downloadPath(accountId: string, id: number, o: { u?: string | null; token?: string | null } = {}): string {
  const p = new URLSearchParams({ account_id: accountId, media_id: String(id) });
  if (o.u) p.set("u", o.u);
  if (o.token) p.set("t", o.token);
  return `/admin/vault-ai/download?${p}`;
}

export function appLink(o: Pick<LinksOpts, "origin" | "accountId" | "token">, id: number): string {
  return `${o.origin.replace(/\/+$/, "")}${downloadPath(o.accountId, id, { token: o.token })}`;
}

export function utcStamp(ms: number): string {
  return new Date(ms).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

export function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export function linkRows(items: DlItem[], o: LinksOpts): LinkRow[] {
  return items.map((it) => {
    const app = appLink(o, it.id);
    const exp = it.url ? urlExpiry(it.url) : null;
    // OF signs vault urls for ~24 h from listing; MIN_LEFT_MS keeps a link from expiring before it is opened.
    const cdn = o.direct && it.url && exp !== null && exp - o.now > MIN_LEFT_MS;
    const link: LinkKind = !it.url ? "drm" : cdn ? "cdn" : "app";
    return { id: it.id, name: it.name, kind: it.kind, folder: it.folder, link,
             href: link === "cdn" ? (it.url as string) : link === "app" ? app : "", app };
  });
}

export function buildLinksFile(items: DlItem[], o: LinksOpts): LinksFile {
  const rows = linkRows(items, o);
  const exps = rows.filter((r) => r.link === "cdn").map((r) => urlExpiry(r.href) as number);
  const validUntil = exps.length ? Math.min(...exps) : null;
  const base = validUntil === null ? "links-valid-while-logged-in"
    : `links-valid-until-${new Date(validUntil).toISOString().slice(0, 16).replace(/[-:]/g, "").replace("T", "-")}UTC`;
  const origin = o.origin.replace(/\/+$/, "");
  const nApp = rows.filter((r) => r.link !== "drm").length;
  const head = [
    `${o.creator}: ${o.label} (${rows.length} files), made ${utcStamp(o.now)}`,
    validUntil === null ? "Valid until: no expiry (app links)" : `Valid until ${utcStamp(validUntil)} (OnlyFans CDN links, signed ~24 h)`,
    ...(nApp ? [`App links (${origin}/admin/...): open while logged in to ${origin}.`] : []),
    ...(validUntil !== null ? ["CDN links open only from the network the app's server uses; if one says Access Denied, use its app link in the .html file."] : []),
  ];
  const txt = [...head.map((l) => `# ${l}`), "",
    ...rows.map((r) => `${r.name}  ${r.link === "drm" ? DRM_TEXT : r.href}`)].join("\n") + "\n";
  const e = escapeHtml;
  const cell = (r: LinkRow) => r.link === "drm" ? `<td>${DRM_TEXT}</td><td></td>`
    : `<td><a href="${e(r.href)}" target="_blank" rel="noopener noreferrer">${r.link === "cdn" ? "Open (CDN)" : "Open (app)"}</a></td>`
      + `<td>${r.link === "cdn" ? `<a href="${e(r.app)}" target="_blank" rel="noopener noreferrer">app link</a>` : ""}</td>`;
  const html = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${e(`${o.creator}: ${o.label}`)}</title>
<style>body{font:14px system-ui,sans-serif;margin:24px;color:#111}p{margin:4px 0;color:#444}table{border-collapse:collapse;margin-top:12px}
td,th{border-bottom:1px solid #ddd;padding:4px 10px;text-align:left}th{background:#f5f5f5}td.m{font-family:ui-monospace,monospace}</style>
</head><body>
<h1>${e(head[0])}</h1>
${head.slice(1).map((l) => `<p>${e(l)}</p>`).join("\n")}
<table><thead><tr><th>#</th><th>File</th><th>Type</th><th>Folder</th><th>Link</th><th>Backup</th></tr></thead><tbody>
${rows.map((r, i) => `<tr data-id="${r.id}" data-link="${r.link}"><td>${i + 1}</td><td class="m">${e(r.name)}</td><td>${e(r.kind)}</td><td>${e(r.folder)}</td>${cell(r)}</tr>`).join("\n")}
</tbody></table>
</body></html>
`;
  return { txtName: `${base}.txt`, htmlName: `${base}.html`, txt, html, validUntil, rows };
}
