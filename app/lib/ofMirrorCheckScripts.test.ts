/**
 * scripts/of-mirror-check runs as `python3 scripts/of-mirror-check/<name>.py`, which puts that directory first on
 * sys.path: a script named after a stdlib module (collections.py, queue.py) shadows it, and Playwright's own imports
 * run that script instead (dead.py crashed on import, or ran queue.py's check). No script may take a stdlib name.
 */
import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const DIR = join(__dirname, "../../scripts/of-mirror-check");
const py = spawnSync("python3", ["-I", "-c", "import sys; print('\\n'.join(sorted(sys.stdlib_module_names)))"], { encoding: "utf8" });

describe("of-mirror-check scripts", () => {
  it.skipIf(py.status !== 0)("no script is named after a Python stdlib module", () => {
    const stdlib = new Set(py.stdout.split("\n").filter(Boolean));
    const scripts = readdirSync(DIR).filter((f) => f.endsWith(".py")).map((f) => f.slice(0, -3));
    expect(scripts).toContain("dead");
    expect(scripts.filter((s) => stdlib.has(s))).toEqual([]);
  });
});
