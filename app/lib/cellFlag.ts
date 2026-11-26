export function cellMode(): boolean {
  return typeof document !== "undefined" && document.querySelector('meta[name="oi-cells"]') != null;
}
