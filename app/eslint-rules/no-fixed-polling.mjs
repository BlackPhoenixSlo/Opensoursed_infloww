/**
 * local/no-fixed-polling — a react-query `refetchInterval` must be
 * `ssePoll(slowMs, fastMs)` (app/lib/events.ts: slow while SSE is live, fast
 * when it drops). Anything else needs a disable comment that says why:
 *   // eslint-disable-next-line local/no-fixed-polling -- <why>
 * A disable for this rule without `-- <why>` is itself reported.
 */
const RULE = "local/no-fixed-polling";
const DIRECTIVE = /^\s*eslint-disable(?:-next-line|-line)?\s+(.*)$/s;

const isSsePoll = (v) =>
  v?.type === "CallExpression" && v.callee.type === "Identifier" && v.callee.name === "ssePoll";

const keyName = (p) =>
  !p.computed && (p.key.type === "Identifier" ? p.key.name : p.key.type === "Literal" ? p.key.value : null);

const rule = {
  meta: {
    type: "problem",
    docs: { description: "refetchInterval must be ssePoll(...) or carry a stated reason" },
    schema: [],
    messages: {
      fixed:
        "fixed polling: use ssePoll(slowMs, fastMs) from app/lib/events, or add " +
        "`// eslint-disable-next-line local/no-fixed-polling -- <why this must poll on a fixed timer>`",
      noReason: "state why: `eslint-disable … local/no-fixed-polling -- <why this must poll on a fixed timer>`",
    },
  },
  create(context) {
    return {
      Program() {
        for (const c of context.sourceCode.getAllComments()) {
          const m = DIRECTIVE.exec(c.value);
          if (!m) continue;
          const [rules, ...why] = m[1].split(/\s-{2,}\s/);
          if (!rules.split(",").some((r) => r.trim() === RULE)) continue;
          if (!why.join(" ").trim()) context.report({ loc: c.loc, messageId: "noReason" });
        }
      },
      Property(node) {
        if (node.parent.type !== "ObjectExpression" || keyName(node) !== "refetchInterval") return;
        if (!isSsePoll(node.value)) context.report({ node, messageId: "fixed" });
      },
    };
  },
};

export default rule;
