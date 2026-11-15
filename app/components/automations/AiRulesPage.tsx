"use client";

/**
 * AI rules (/ai-rules): the Full AI Turn as a zoomable diagram, read from GET /admin/full-ai/rules?mode=test|shadow.
 * Every prompt, question, table and switch on a card comes from the live code objects (service/automations/
 * full_ai_rules.py). Wheel zooms at the pointer, drag pans, two fingers pinch, keys + / - / 0; a click opens the card
 * in a drawer (bottom sheet on phone) with the full text. View state: aiRulesView.ts; positions: aiRulesLayout.ts.
 */
import { useEffect, useMemo, useReducer, useRef } from "react";
import { PageFrame } from "@/components/shell/PageFrame";
import { relay } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { layout } from "./aiRulesLayout";
import {
  aiRulesReducer, DETAIL_K, INITIAL, orientationFor,
  type Action, type Mode, type RuleBlock, type RuleNode, type Rules,
} from "./aiRulesView";

const BTN = "h-8 min-w-8 rounded-md border border-border bg-bg-elev-1 px-2 text-[13px] text-fg hover:bg-bg-elev-2";
const DRAG_PX = 4;

export default function AiRulesPage() {
  const [s, dispatch] = useReducer(aiRulesReducer, INITIAL);
  const box = useRef<HTMLDivElement>(null);
  const orientation = orientationFor(s.viewport.w);
  const lay = useMemo(() => (s.data ? layout(s.data.nodes, s.data.edges, orientation) : null), [s.data, orientation]);

  useEffect(() => {
    let live = true;
    relay.get<Rules>(`/admin/full-ai/rules?mode=${s.mode}`, { priority: "background" })
      .then((data) => live && dispatch({ type: "loaded", mode: s.mode, data }))
      .catch((e: unknown) => live && dispatch({ type: "failed", mode: s.mode, error: e instanceof Error ? e.message : String(e) }));
    return () => { live = false; };
  }, [s.mode]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => dispatch({ type: "resize", w: el.clientWidth, h: el.clientHeight });
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // A new diagram (reducer's pendingFit) fits once; later resizes keep the view.
  useEffect(() => {
    if (s.pendingFit && lay) dispatch({ type: "fit", w: lay.width, h: lay.height });
  }, [s.pendingFit, lay]);

  const { handlers, dragged } = useGestures(box, dispatch);
  const fit = () => lay && dispatch({ type: "fit", w: lay.width, h: lay.height });
  const selected = s.data?.nodes.find((n) => n.id === s.selected) ?? null;
  const detail = s.view.k >= DETAIL_K;

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "+" || e.key === "=") dispatch({ type: "zoomStep", dir: 1 });
    else if (e.key === "-" || e.key === "_") dispatch({ type: "zoomStep", dir: -1 });
    else if (e.key === "0") fit();
    else if (e.key === "Escape") dispatch({ type: "close" });
    else return;
    e.preventDefault();
  };

  return (
    <PageFrame title="AI rules">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <button type="button" className={BTN} aria-label="Zoom out" onClick={() => dispatch({ type: "zoomStep", dir: -1 })}>−</button>
        <button type="button" className={BTN} aria-label="Zoom in" onClick={() => dispatch({ type: "zoomStep", dir: 1 })}>+</button>
        <button type="button" className={BTN} onClick={fit}>Fit</button>
        <div role="group" aria-label="Mode" className="flex overflow-hidden rounded-md border border-border">
          {(["test", "shadow"] as Mode[]).map((m) => (
            <button key={m} type="button" aria-pressed={s.mode === m}
              onClick={() => dispatch({ type: "setMode", mode: m })}
              className={cn("h-8 px-3 text-[13px]", s.mode === m ? "bg-accent text-white" : "bg-bg-elev-1 text-fg-dim hover:bg-bg-elev-2")}>
              {m === "test" ? "Test" : "Shadow"}
            </button>
          ))}
        </div>
        <span className="text-[12px] text-muted">
          {s.status === "loading" ? "Loading…" : s.status === "error" ? <span className="text-err">{s.error}</span>
            : `${Math.round(s.view.k * 100)}% · drag to pan, wheel or pinch to zoom, click a card`}
        </span>
      </div>

      <div ref={box} tabIndex={0} onKeyDown={onKey} {...handlers}
        aria-label="AI rules diagram"
        className="relative h-[calc(100dvh-150px)] min-h-[420px] touch-none select-none overflow-hidden rounded-lg border border-border bg-hb-bg outline-none focus-visible:border-accent">
        {lay && s.data && (
          <div className="absolute left-0 top-0 origin-top-left"
            style={{ width: lay.width, height: lay.height, transform: `translate(${s.view.x}px, ${s.view.y}px) scale(${s.view.k})` }}>
            <svg className="absolute inset-0 overflow-visible" width={lay.width} height={lay.height} aria-hidden>
              {lay.edges.map((e, i) => (
                <path key={i} d={e.path} fill="none" strokeWidth={2}
                  className={e.back ? "stroke-accent" : "stroke-border-light"} strokeDasharray={e.back ? "6 6" : undefined} />
              ))}
              {lay.edges.map((e, i) => (
                <text key={`t${i}`} x={e.labelX} y={e.labelY} textAnchor="middle" dominantBaseline="middle"
                  className="fill-fg-dim stroke-hb-bg text-[13px]" strokeWidth={5} paintOrder="stroke">{e.label}</text>
              ))}
            </svg>
            {s.data.nodes.map((n) => {
              const b = lay.boxes[n.id];
              return b && (
                <Card key={n.id} node={n} detail={detail} selected={n.id === s.selected}
                  style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
                  onClick={() => { if (!dragged()) dispatch({ type: "select", id: n.id }); }}
                  onOpen={() => dispatch({ type: "select", id: n.id })} />
              );
            })}
          </div>
        )}
      </div>
      {s.data && (
        <p className="mt-1 text-[11px] text-muted">
          {Object.entries(s.data.versions).map(([k, v]) => `${k} ${v}`).join(" · ")}
        </p>
      )}

      {selected && <Drawer node={selected} onClose={() => dispatch({ type: "close" })} />}
    </PageFrame>
  );
}

/** Pointer gestures on the viewport: one pointer pans, two pinch (zoom at their midpoint + pan); the wheel zooms at
 *  the cursor. A press that moves past DRAG_PX is a drag, so its release doesn't open a card. */
function useGestures(box: React.RefObject<HTMLDivElement | null>, dispatch: React.Dispatch<Action>) {
  const pts = useRef(new Map<number, { x: number; y: number }>());
  const moved = useRef(0);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      dispatch({ type: "zoomAt", px: e.clientX - r.left, py: e.clientY - r.top, factor: Math.exp(-dy * 0.0015) });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [box, dispatch]);

  const local = (e: React.PointerEvent) => {
    const r = box.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const drop = (e: React.PointerEvent) => { pts.current.delete(e.pointerId); };
  const handlers = {
    onPointerDown: (e: React.PointerEvent) => {
      if (pts.current.size === 0) moved.current = 0;
      pts.current.set(e.pointerId, local(e));
    },
    onPointerMove: (e: React.PointerEvent) => {
      const prev = pts.current.get(e.pointerId);
      if (!prev) return;
      // A mouse released outside before the drag captured it: forget it, so hovering never pans.
      if (e.pointerType === "mouse" && e.buttons === 0) { drop(e); return; }
      const now = local(e);
      if (pts.current.size >= 2) {
        const [a, b] = [...pts.current.entries()];
        const other = a[0] === e.pointerId ? b[1] : a[1];
        const d0 = Math.hypot(prev.x - other.x, prev.y - other.y);
        const d1 = Math.hypot(now.x - other.x, now.y - other.y);
        const c0 = { x: (prev.x + other.x) / 2, y: (prev.y + other.y) / 2 };
        const c1 = { x: (now.x + other.x) / 2, y: (now.y + other.y) / 2 };
        moved.current += DRAG_PX + 1;
        if (d0 > 0) dispatch({ type: "pinch", cx: c0.x, cy: c0.y, ratio: d1 / d0, dx: c1.x - c0.x, dy: c1.y - c0.y });
      } else {
        moved.current += Math.hypot(now.x - prev.x, now.y - prev.y);
        if (moved.current > DRAG_PX) {
          // Capture only once it is a drag, so a plain click still lands on the card.
          if (!box.current!.hasPointerCapture?.(e.pointerId)) box.current!.setPointerCapture?.(e.pointerId);
          dispatch({ type: "panBy", dx: now.x - prev.x, dy: now.y - prev.y });
        }
      }
      pts.current.set(e.pointerId, now);
    },
    onPointerUp: drop,
    onPointerCancel: drop,
  };
  return { handlers, dragged: () => moved.current > DRAG_PX };
}

/** `onClick` (pointer, drag-guarded by the page) and `onOpen` (keyboard) both open the drawer. */
function Card({ node, detail, selected, style, onClick, onOpen }: {
  node: RuleNode; detail: boolean; selected: boolean; style: React.CSSProperties; onClick: () => void; onOpen: () => void;
}) {
  return (
    <div role="button" tabIndex={0} aria-label={node.title} style={style}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); onOpen(); } }}
      className={cn("absolute flex cursor-pointer flex-col overflow-hidden rounded-lg border bg-bg-elev-1 p-3 text-left shadow-lg",
        selected ? "border-accent" : "border-border hover:border-border-light")}>
      {detail ? (
        <>
          <h3 className="text-[15px] font-semibold text-fg">{node.title}</h3>
          <p className="mt-1 line-clamp-2 text-[12px] text-fg-dim">{node.summary}</p>
          {node.flags.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {node.flags.map((f) => <Chip key={f.key}>{f.label}</Chip>)}
            </div>
          )}
          <div className="mt-2 min-h-0 flex-1 space-y-1.5 overflow-hidden">
            {node.blocks.map((b, i) => (
              <div key={i}>
                <div className="text-[11px] font-medium text-muted">{b.label}</div>
                <pre className="line-clamp-2 whitespace-pre-wrap break-words font-mono text-[11px] text-fg-dim">{preview(b)}</pre>
              </div>
            ))}
          </div>
          <div className="pt-1 text-[11px] text-muted">{node.blocks.length} blocks · open</div>
        </>
      ) : (
        // Zoomed out: big title + summary only, so the overview still reads.
        <>
          <h3 className="text-[34px] font-semibold leading-tight text-fg">{node.title}</h3>
          <p className="mt-2 line-clamp-4 text-[18px] text-fg-dim">{node.summary}</p>
        </>
      )}
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return <span className="rounded bg-bg-elev-2 px-1.5 py-0.5 text-[10px] text-fg-dim">{children}</span>;
}

function preview(b: RuleBlock): string {
  if (b.text) return b.text;
  if (b.items) return b.items.join(" · ");
  if (b.rows) return b.rows.slice(1).map((r) => r.join(" | ")).join("\n");
  return "";
}

function Drawer({ node, onClose }: { node: RuleNode; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.focus(); }, [node.id]);
  return (
    <div ref={ref} role="dialog" aria-label={node.title} tabIndex={-1}
      onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
      className="fixed inset-x-0 bottom-0 z-50 flex max-h-[75dvh] select-text flex-col rounded-t-xl border border-border bg-panel shadow-2xl outline-none md:inset-y-0 md:left-auto md:right-0 md:max-h-none md:w-[600px] md:rounded-none md:rounded-l-xl">
      <div className="flex items-start gap-2 border-b border-border p-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-[16px] font-semibold text-fg">{node.title}</h2>
          <p className="mt-1 text-[13px] text-fg-dim">{node.summary}</p>
          {node.flags.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {node.flags.map((f) => <Chip key={f.key}>{f.label} · {f.key} · default {String(f.default)}</Chip>)}
            </div>
          )}
        </div>
        <button type="button" className={BTN} aria-label="Close" onClick={onClose}>✕</button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {node.blocks.map((b, i) => <BlockView key={i} b={b} />)}
      </div>
    </div>
  );
}

function BlockView({ b }: { b: RuleBlock }) {
  return (
    <section>
      <div className="flex flex-wrap items-center gap-1.5">
        <h3 className="text-[13px] font-semibold text-fg">{b.label}</h3>
        {b.flag && <Chip>flag {b.flag}</Chip>}
        {b.doc && <Chip>{b.doc}</Chip>}
      </div>
      <div className="mb-1 font-mono text-[11px] text-muted">{b.source}</div>
      {b.text !== undefined && (
        <pre className="whitespace-pre-wrap break-words rounded-md bg-bg-elev-1 p-2 font-mono text-[12px] text-fg-dim">{b.text}</pre>
      )}
      {b.items && (
        <ul className="list-disc space-y-0.5 pl-5 font-mono text-[12px] text-fg-dim">
          {b.items.map((it, i) => <li key={i} className="whitespace-pre-wrap break-words">{it}</li>)}
        </ul>
      )}
      {b.rows && b.rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse font-mono text-[12px]">
            <thead>
              <tr>{b.rows[0].map((c, i) => <th key={i} className="border-b border-border px-2 py-1 text-left text-muted">{c}</th>)}</tr>
            </thead>
            <tbody>
              {b.rows.slice(1).map((r, i) => (
                <tr key={i}>{r.map((c, j) => <td key={j} className="border-b border-border px-2 py-1 align-top whitespace-pre-wrap break-words text-fg-dim">{c}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
