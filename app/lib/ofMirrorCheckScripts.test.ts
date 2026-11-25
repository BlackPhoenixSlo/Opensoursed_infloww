import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const DIR = join(__dirname, "../../scripts/of-mirror-check");
const py = spawnSync("python3", ["-I", "-c", "import sys; print('\\n'.join(sorted(sys.stdlib_module_names)))"], { encoding: "utf8" });

describe("of-mirror-check scripts", () => {
  // A script named after a stdlib module shadows it on sys.path (dead.py crashed on import).
  it.skipIf(py.status !== 0)("no script is named after a Python stdlib module", () => {
    const stdlib = new Set(py.stdout.split("\n").filter(Boolean));
    const scripts = readdirSync(DIR).filter((f) => f.endsWith(".py")).map((f) => f.slice(0, -3));
    expect(scripts).toContain("dead");
    expect(scripts.filter((s) => stdlib.has(s))).toEqual([]);
  });
});
