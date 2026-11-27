import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";

import { routeOf } from "@/lib/cellRoute";

const CTX_ARG: Record<string, number> = { get: 1, delete: 1, post: 2, patch: 2, put: 2, uploadForm: 2, uploadFile: 3 };
const DEPTH = 6;
const MAX_SAMPLES = 16;

export interface CallSite {
  file: string;
  line: number;
  method: string;
  path: string;
  verdict: "routed" | "unrouted" | "ctx" | "dynamic";
}

type Named = "named" | "none" | "opaque";

function bare(n: ts.Expression): ts.Expression {
  while (ts.isParenthesizedExpression(n) || ts.isNonNullExpression(n) || ts.isAsExpression(n)
    || ts.isSatisfiesExpression(n)) n = n.expression;
  return n;
}

const product = (a: string[], b: string[]) => a.flatMap((x) => b.map((y) => x + y)).slice(0, MAX_SAMPLES);

const propName = (p: ts.ObjectLiteralElementLike) =>
  p.name && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name)) ? p.name.text : null;

const isNothing = (n: ts.Expression) => n.kind === ts.SyntaxKind.NullKeyword
  || n.kind === ts.SyntaxKind.UndefinedKeyword || (ts.isIdentifier(n) && n.text === "undefined");

class Resolver {
  constructor(private checker: ts.TypeChecker) {}

  private decl(id: ts.Identifier): ts.Declaration | undefined {
    return this.checker.getSymbolAtLocation(id)?.valueDeclaration;
  }

  private constInit(n: ts.Expression): ts.Expression | null {
    if (!ts.isIdentifier(n)) return null;
    const d = this.decl(n);
    return d && ts.isVariableDeclaration(d) && d.initializer
      && (ts.getCombinedNodeFlags(d) & ts.NodeFlags.Const) ? d.initializer : null;
  }

  private returns(call: ts.CallExpression): ts.Expression[] | null {
    if (!ts.isIdentifier(call.expression)) return null;
    const d = this.decl(call.expression);
    const fn = d && ts.isFunctionDeclaration(d) ? d : d && ts.isVariableDeclaration(d) ? d.initializer : undefined;
    if (!fn || !(ts.isFunctionDeclaration(fn) || ts.isArrowFunction(fn) || ts.isFunctionExpression(fn)) || !fn.body) {
      return null;
    }
    if (!ts.isBlock(fn.body)) return [fn.body];
    const out: ts.Expression[] = [];
    let bareReturn = false;
    const visit = (n: ts.Node) => {
      if (ts.isReturnStatement(n)) {
        if (n.expression) out.push(n.expression);
        else bareReturn = true;
      } else if (!ts.isFunctionLike(n)) ts.forEachChild(n, visit);
    };
    visit(fn.body);
    return out.length && !bareReturn ? out : null;
  }

  private object(n: ts.Expression, d: number): ts.ObjectLiteralExpression | null {
    const init = this.constInit(bare(n));
    const o = init && bare(init);
    return o && ts.isObjectLiteralExpression(o) && d < DEPTH ? o : null;
  }

  samples(node: ts.Expression, d = 0): string[] | null {
    if (d > DEPTH) return null;
    const n = bare(node);
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) return [n.text];
    if (ts.isTemplateExpression(n)) {
      let acc = [n.head.text];
      for (const s of n.templateSpans) {
        acc = product(product(acc, this.samples(s.expression, d + 1) ?? this.query(s.expression, d + 1) ?? ["1"]),
          [s.literal.text]);
      }
      return acc;
    }
    if (ts.isConditionalExpression(n)) {
      const a = this.samples(n.whenTrue, d + 1);
      const b = this.samples(n.whenFalse, d + 1);
      return a && b ? [...a, ...b].slice(0, MAX_SAMPLES) : null;
    }
    if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      const a = this.samples(n.left, d + 1);
      const b = this.samples(n.right, d + 1);
      return a && b ? product(a, b) : null;
    }
    if (ts.isIdentifier(n)) {
      const init = this.constInit(n);
      return init ? this.samples(init, d + 1) : null;
    }
    if (ts.isPropertyAccessExpression(n) || ts.isElementAccessExpression(n)) {
      const o = this.object(n.expression, d);
      if (!o) return null;
      const want = ts.isPropertyAccessExpression(n) ? n.name.text : null;
      const out: string[] = [];
      for (const p of o.properties) {
        if (!ts.isPropertyAssignment(p) || (want !== null && propName(p) !== want)) continue;
        const s = this.samples(p.initializer, d + 1);
        if (!s) return null;
        out.push(...s);
      }
      return out.length ? out.slice(0, MAX_SAMPLES) : null;
    }
    if (ts.isCallExpression(n)) {
      const rets = this.returns(n);
      if (!rets) return null;
      const out: string[] = [];
      for (const r of rets) {
        const s = this.samples(r, d + 1);
        if (!s) return null;
        out.push(...s);
      }
      return out.slice(0, MAX_SAMPLES);
    }
    return null;
  }

  private query(node: ts.Expression, d: number): string[] | null {
    if (d > DEPTH) return null;
    const n = bare(node);
    if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && n.expression.name.text === "toString"
      && !n.arguments.length) return this.query(n.expression.expression, d + 1);
    if (ts.isCallExpression(n)) {
      const rets = this.returns(n);
      const all = rets?.map((r) => this.query(r, d + 1));
      return all?.every((q) => q !== null) ? all.flatMap((q) => q!).slice(0, MAX_SAMPLES) : null;
    }
    const keys = (e: ts.Expression) => {
      const x = bare(e);
      if (!ts.isNewExpression(x) || !ts.isIdentifier(x.expression) || x.expression.text !== "URLSearchParams") return null;
      const a = x.arguments?.[0] && bare(x.arguments[0]);
      const o = a && (ts.isObjectLiteralExpression(a) ? a : this.object(a, d));
      return o ? o.properties.map(propName).filter((k): k is string => k !== null) : [];
    };
    const direct = keys(n);
    if (direct) return [direct.map((k) => `${k}=1`).join("&")];
    if (!ts.isIdentifier(n)) return null;
    const init = this.constInit(n);
    const base = init && keys(init);
    if (!base) return null;
    const stmt = this.decl(n)!.parent.parent;
    const block = stmt.parent;
    if (ts.isBlock(block) || ts.isSourceFile(block)) {
      for (const s of block.statements) {
        if (!ts.isExpressionStatement(s) || !ts.isCallExpression(s.expression)) continue;
        const c = s.expression;
        if (ts.isPropertyAccessExpression(c.expression) && ts.isIdentifier(c.expression.expression)
          && c.expression.expression.text === n.text && ["set", "append"].includes(c.expression.name.text)
          && c.arguments[0] && ts.isStringLiteral(c.arguments[0])) base.push(c.arguments[0].text);
      }
    }
    return [base.map((k) => `${k}=1`).join("&")];
  }

  ctx(node: ts.Expression | undefined, d = 0): Named {
    if (!node || isNothing(bare(node))) return "none";
    if (d > DEPTH) return "opaque";
    const n = bare(node);
    if (ts.isIdentifier(n)) {
      const init = this.constInit(n);
      return init ? this.ctx(init, d + 1) : "opaque";
    }
    if (ts.isConditionalExpression(n)) {
      const both = [this.ctx(n.whenTrue, d + 1), this.ctx(n.whenFalse, d + 1)];
      return both.includes("none") ? "none" : both.includes("opaque") ? "opaque" : "named";
    }
    if (ts.isCallExpression(n)) {
      const rets = this.returns(n);
      if (!rets) return "opaque";
      const all = rets.map((r) => this.ctx(r, d + 1));
      return all.includes("none") ? "none" : all.includes("opaque") ? "opaque" : "named";
    }
    if (!ts.isObjectLiteralExpression(n)) return "opaque";
    let spread = false;
    for (const p of n.properties) {
      const name = propName(p);
      if ((name === "accountId" || name === "cellAccountId" || name === "cellId")
        && (ts.isShorthandPropertyAssignment(p) || (ts.isPropertyAssignment(p) && !isNothing(bare(p.initializer))))) {
        return "named";
      }
      if (ts.isSpreadAssignment(p)) {
        const r = this.ctx(p.expression, d + 1);
        if (r === "named") return "named";
        if (r === "opaque") spread = true;
      }
    }
    return spread ? "opaque" : "none";
  }
}

function walk(dir: string, out: string[]): void {
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.name === "node_modules" || e.name.startsWith(".")) continue;
    const p = join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name) && !e.name.endsWith(".d.ts")) out.push(p);
  }
}

function httpMethodOf(method: string, hasBody: boolean): string {
  if (method === "file") return hasBody ? "POST" : "GET";
  return method.startsWith("upload") ? "POST" : method.toUpperCase();
}

export function scanCallSites(root: string): CallSite[] {
  const all: string[] = [];
  walk(root, all);
  const files = all.filter((f) => /\brelay(?:\.|File\()/.test(readFileSync(f, "utf8")));
  const program = ts.createProgram(files, {
    noResolve: true, noLib: true, types: [], jsx: ts.JsxEmit.Preserve, target: ts.ScriptTarget.Latest,
  });
  const r = new Resolver(program.getTypeChecker());
  const sites: CallSite[] = [];
  for (const file of files) {
    const src = program.getSourceFile(file)!;
    const visit = (n: ts.Node) => {
      if (ts.isCallExpression(n)) {
        const c = n.expression;
        let method: string | null = null;
        if (ts.isPropertyAccessExpression(c) && ts.isIdentifier(c.expression) && c.expression.text === "relay"
          && c.name.text in CTX_ARG) method = c.name.text;
        else if (ts.isIdentifier(c) && c.text === "relayFile") method = "file";
        if (method && n.arguments.length) {
          const sampled = r.samples(n.arguments[0]);
          const paths = sampled?.every((p) => p.startsWith("/")) ? sampled : null;
          const ctx = r.ctx(n.arguments[method === "file" ? 1 : CTX_ARG[method]]);
          const none = new Headers();
          const verdict = ctx === "named" ? "routed" : paths === null ? "dynamic"
            : paths.every((p) => routeOf(p, none, httpMethodOf(method, !!n.arguments[2])) !== null) ? "routed" : ctx === "opaque" ? "ctx" : "unrouted";
          sites.push({
            file: relative(root, file), line: src.getLineAndCharacterOfPosition(n.getStart()).line + 1, method,
            path: paths ? paths.join(" | ") : n.arguments[0].getText(src).replace(/\s+/g, " "), verdict,
          });
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(src);
  }
  return sites;
}
