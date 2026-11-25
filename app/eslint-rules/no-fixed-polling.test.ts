// @vitest-environment node
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const APP = resolve(__dirname, "..");
const eslint = new ESLint({ cwd: APP });

async function hits(body: string): Promise<string[]> {
  const src = `import { useQuery } from "@tanstack/react-query";\nimport { ssePoll } from "@/lib/events";\n` +
    `const MS = 60_000;\nexport function useX() {\n  return useQuery({\n    queryKey: ["x"],\n    queryFn: () => 1,\n${body}\n  });\n}\n`;
  const [r] = await eslint.lintText(src, { filePath: resolve(APP, "hooks/__no_fixed_polling_fixture__.ts") });
  return r.messages.filter((m) => m.ruleId === "local/no-fixed-polling").map((m) => m.message);
}

const R = "// eslint-disable-next-line local/no-fixed-polling";

describe("local/no-fixed-polling", () => {
  it.each([
    ["ssePoll call", "    refetchInterval: ssePoll(5 * 60_000, 60_000),"],
    ["ssePoll or off", "    refetchInterval: MS > 0 ? ssePoll(5 * 60_000, 60_000) : false,"],
    ["off or ssePoll", "    refetchInterval: MS > 0 ? false : ssePoll(5 * 60_000, 60_000),"],
    ["disable with reason", `    ${R} -- stops when the job ends\n    refetchInterval: 60_000,`],
    ["not refetchInterval", "    staleTime: 60_000,"],
  ])("valid: %s", async (_n, body) => {
    expect(await hits(body)).toEqual([]);
  });

  it.each([
    ["number literal", "    refetchInterval: 60_000,", /^fixed polling/],
    ["variable", "    refetchInterval: MS,", /^fixed polling/],
    ["arrow function", "    refetchInterval: (q) => (q.state.data ? 1500 : false),", /^fixed polling/],
    ["ssePoll or a fixed interval", "    refetchInterval: MS > 0 ? ssePoll(5 * 60_000, 60_000) : 60_000,", /^fixed polling/],
    ["disable without reason", `    ${R}\n    refetchInterval: 60_000,`, /^state why/],
    ["disable with empty reason", `    ${R} --  \n    refetchInterval: 60_000,`, /^state why/],
  ])("invalid: %s", async (_n, body, msg) => {
    const m = await hits(body);
    expect(m).toHaveLength(1);
    expect(m[0]).toMatch(msg);
  });

  it("every disable of the rule in app/ states a reason", () => {
    let out = "";
    try {
      out = execFileSync("git", ["grep", "-n", "-E", "eslint-disable.*local/no-fixed-polling", "--", ".",
        ":!eslint-rules/"], { cwd: APP, encoding: "utf8" });
    } catch { }
    const bare = out.split("\n").filter((l) => l && !/\s--+\s+\S/.test(l.slice(l.indexOf("no-fixed-polling"))));
    expect(bare).toEqual([]);
  });
});
