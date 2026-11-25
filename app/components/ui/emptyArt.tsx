// Redrawn as SVG: never copy Infloww's CDN PNGs.
export type EmptyKind = "data" | "search" | "creator" | "schedule" | "error";

const BODY = "fill-[#5f5f5f] [html[data-theme=light]_&]:fill-[#e4e4e4]";
const RIM = "stroke-[#9f9f9f] [html[data-theme=light]_&]:stroke-[#c4c4c4]";
const INK = "fill-[#9f9f9f] [html[data-theme=light]_&]:fill-[#c4c4c4]";
const LINE = "stroke-[#9f9f9f] [html[data-theme=light]_&]:stroke-[#c4c4c4]";
const RAY = "stroke-[#3d3d3d] [html[data-theme=light]_&]:stroke-[#e6e6e6]";
const FACE = "#3467ff";

function Face({ kind }: { kind: EmptyKind }) {
  const eye = { stroke: FACE, strokeWidth: 4, strokeLinecap: "round" as const };
  switch (kind) {
    case "search":
      return (
        <g {...eye} fill="none" strokeWidth={3.5}>
          <circle cx={62} cy={62} r={9} />
          <path d="M69 69l7 7" />
        </g>
      );
    case "creator":
      return (
        <g {...eye} fill="none" strokeWidth={3.5}>
          <circle cx={64.5} cy={57} r={6} />
          <path d="M53 77c2-7 6.5-10 11.5-10s9.5 3 11.5 10" />
        </g>
      );
    case "schedule":
      return (
        <g {...eye} fill="none" strokeWidth={3.5}>
          <circle cx={64.5} cy={64} r={11} />
          <path d="M64.5 58v6.5l4.5 3" />
        </g>
      );
    case "error":
      return (
        <g {...eye}>
          <path d="M49 54l7 5M56 54l-7 5M73 54l7 5M80 54l-7 5" />
          <path d="M56 77c3-3 6-4.5 8.5-4.5s5.5 1.5 8.5 4.5" fill="none" />
        </g>
      );
    default:
      return (
        <g {...eye}>
          <path d="M49.5 56.5h9M71 56.5h9M56.5 74h16" />
        </g>
      );
  }
}

export function EmptyArt({ kind = "data", height = 100 }: { kind?: EmptyKind; height?: number }) {
  return (
    <svg
      aria-hidden
      focusable="false"
      data-empty-art={kind}
      viewBox="0 0 125 100"
      height={height}
      width={(height * 125) / 100}
      className="block"
    >
      <g className={RAY} strokeWidth={2.2} strokeLinecap="round" fill="none">
        <path d="M27.5 8.5l4.5 6M37.5 7.5l1 4M23 17l5.5 2M97 8.5l-4.5 6M87 7.5l-1 4M101.5 17l-5.5 2" />
      </g>
      <g className={INK}>
        <circle cx={101} cy={25} r={1.3} />
        <circle cx={109} cy={41.5} r={1.8} />
        <circle cx={25} cy={46.5} r={1.3} />
        <circle cx={17.5} cy={61} r={2.4} />
      </g>
      <path
        d="M41 19.5h38.5L95.5 35.5v49a7 7 0 0 1-7 7H41a7 7 0 0 1-7-7v-58a7 7 0 0 1 7-7z"
        className={`${BODY} ${RIM}`}
        strokeWidth={2.4}
        strokeLinejoin="round"
      />
      <path d="M79.5 19.5v9a7 7 0 0 0 7 7h9z" className={INK} />
      <g className={LINE} strokeWidth={3.4} strokeLinecap="round" fill="none">
        <path d="M41 29.5h26.5M41 36h22M41 43.5h12.5" />
      </g>
      <Face kind={kind} />
    </svg>
  );
}
