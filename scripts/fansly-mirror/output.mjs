import fs from "node:fs";
import path from "node:path";

export function install({ stage, out, old, files }) {
  for (const [file, text] of files) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(`${file}.tmp`, text);
  }
  fs.mkdirSync(path.dirname(out), { recursive: true });
  if (fs.existsSync(out)) fs.renameSync(out, old);
  fs.renameSync(stage, out);
  for (const [file] of files) fs.renameSync(`${file}.tmp`, file);
  fs.rmSync(old, { recursive: true, force: true });
}

export function printSummary({ pages, build, people, sections, stats, hidden, canvases, dropped, entries, unwired }) {
  console.log(`fansly-mirror: ${pages.length} pages written, build ${build}, ${people} other people scrubbed`);
  for (const s of sections) console.log(`  ${s}: ${pages.filter((p) => p.section === s).length}`);
  console.log(`  assets: ${stats.copied} copied, ${stats.bytes} bytes`);
  for (const line of [...stats.blanked, ...hidden]) console.log(`  ${line}`);
  console.log(`  canvases replaced: ${canvases}`);
  for (const line of dropped) console.log(`  not captured, dropped: ${line}`);
  for (const line of unwired) console.log(`  not mirrored, left dead: ${line}`);
  for (const e of entries) if (e.shadow_roots || e.iframes) console.log(`  entry ${e.id}: ${Number(e.shadow_roots) || 0} shadow roots, ${Number(e.iframes) || 0} iframes`);
}
