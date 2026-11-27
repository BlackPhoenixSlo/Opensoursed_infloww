let enabled: boolean | undefined;

export function cellMode(): boolean {
  if (typeof document === "undefined") return false;
  return enabled ??= document.querySelector('meta[name="oi-cells"]') != null;
}

export function resetCellFlagForTests(): void {
  enabled = undefined;
}
