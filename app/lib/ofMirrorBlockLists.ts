import { closeMenu, showMenu } from "@/lib/ofMirrorMenu";
import { SETTINGS_READ } from "@/lib/ofMirrorSettings";
import { countryPicker, countryPickerNotYet, drawCountries, ipForm, ipFormNotYet, showIps } from "@/lib/ofMirrorSettingsPages";
import type { NewWriteBinding, NewWriteEnv } from "@/lib/ofMirrorSettingsWrites";
import { toast } from "@/lib/ofMirrorToast";
import { message, note, ofConfirm, SAVED_TOAST, type Ask } from "@/lib/ofMirrorWrites";

export const BLOCKED_COUNTRIES = "/api/of/v2/users/me/settings/security/blocked-countries";
export const BLOCKED_IPS = "/api/of/v2/users/me/settings/security/blocked-ips";

export interface Country {
  code: string;
  name: string;
}

export function countriesOf(read: unknown): Country[] {
  if (!Array.isArray(read)) return [];
  return read.flatMap((c) =>
    c && typeof c === "object" && typeof c.code === "string" && typeof c.name === "string" ? [{ code: c.code, name: c.name }] : [],
  );
}

export interface Blocked {
  countries: string[];
  states: number[];
  ips: string[];
}

export function blockedOf(settings: unknown): Blocked | null {
  if (!settings || typeof settings !== "object" || Array.isArray(settings)) return null;
  const s = settings as Record<string, unknown>;
  const list = <T>(v: unknown, ok: (x: unknown) => x is T): T[] => (Array.isArray(v) ? v.filter(ok) : []);
  const str = (x: unknown): x is string => typeof x === "string";
  const int = (x: unknown): x is number => Number.isInteger(x);
  return { countries: list(s.blockedCountries, str), states: list(s.blockedStates, int), ips: list(s.blockedIps, str) };
}

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));


export interface CountryState {
  initial: string[];
  picked: string[];
  states: number[];
  search: string;
  saving: boolean;
  loaded: boolean;
}

export type CountryAction =
  | { type: "load"; countries: string[]; states: number[] }
  | { type: "toggle"; code: string }
  | { type: "search"; text: string }
  | { type: "reset" }
  | { type: "save" }
  | { type: "saved" }
  | { type: "failed" };

export const countryInit = (b: Pick<Blocked, "countries" | "states"> | null): CountryState => ({
  initial: [...(b?.countries ?? [])],
  picked: [...(b?.countries ?? [])],
  states: [...(b?.states ?? [])],
  search: "",
  saving: false,
  loaded: b !== null,
});

export const countryDirty = (s: CountryState) => !sameSet(s.initial, s.picked);
// Save stays off until a settings read lands: a Save then would PUT empty lists over OF's.
export const canSubmitCountries = (s: CountryState) => s.loaded && !s.saving && countryDirty(s);

export function countryReducer(s: CountryState, a: CountryAction): CountryState {
  switch (a.type) {
    case "load":
      return s.saving || countryDirty(s) ? s : { ...countryInit({ countries: a.countries, states: a.states }), search: s.search };
    case "toggle":
      if (s.saving || !s.loaded) return s;
      return { ...s, picked: s.picked.includes(a.code) ? s.picked.filter((c) => c !== a.code) : [...s.picked, a.code] };
    case "search":
      return s.loaded ? { ...s, search: a.text } : s;
    case "reset":
      return s.saving ? s : { ...s, picked: [...s.initial], search: "" };
    case "save":
      return canSubmitCountries(s) ? { ...s, saving: true } : s;
    case "saved":
      return { ...s, initial: [...s.picked], search: "", saving: false };
    case "failed":
      return { ...s, picked: [...s.initial], saving: false };
  }
}

// blockedStates goes back as read: the states picker is not built.
export const countryPayload = (s: CountryState) => ({ blockedCountries: [...s.picked], blockedStates: [...s.states] });

export function filterCountries(list: Country[], search: string): Country[] {
  const q = search.trim().toLowerCase();
  return q ? list.filter((c) => c.name.toLowerCase().includes(q)) : list;
}

export const countryName = (list: Country[], code: string) => list.find((c) => c.code === code)?.name ?? code;

export const countryAsk = (names: string[]): Ask => ({
  title: "Block by country?",
  text: names.length
    ? `People in ${names.join(", ")} will not be able to see your profile or posts.`
    : "No country will be blocked.",
  ok: "Save",
});


const OCTET = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/;

export function isIpEntry(entry: string): boolean {
  const [addr, bits, extra] = entry.split("/");
  if (extra !== undefined || addr === "") return false;
  if (bits !== undefined && !/^\d{1,3}$/.test(bits)) return false;
  const parts = addr.split(".");
  if (parts.length === 4) {
    const wild = parts.includes("*");
    return parts.every((p) => p === "*" || OCTET.test(p)) && (bits === undefined || (!wild && Number(bits) <= 32));
  }
  if (!addr.includes(":") || !/^[0-9a-fA-F:.]+$/.test(addr)) return false;
  if (bits !== undefined && Number(bits) > 128) return false;
  try {
    return new URL(`http://[${addr}]/`).hostname !== "";
  } catch {
    return false;
  }
}

export const ipLines = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

export const badIps = (text: string) => ipLines(text).filter((l) => !isIpEntry(l));

export const ipText = (ips: string[]) => ips.join("\n");

export interface IpState {
  saved: string[];
  text: string;
  saving: boolean;
  loaded: boolean;
}

export type IpAction =
  | { type: "load"; ips: string[] }
  | { type: "edit"; text: string }
  | { type: "cancel" }
  | { type: "save" }
  | { type: "saved" }
  | { type: "failed" };

export const ipInit = (ips: string[] | null): IpState => ({ saved: [...(ips ?? [])], text: ipText(ips ?? []), saving: false, loaded: ips !== null });

export const ipDirty = (s: IpState) => s.text !== ipText(s.saved);
export const canCancelIps = (s: IpState) => !s.saving && ipDirty(s);
export const canSubmitIps = (s: IpState) => {
  const lines = ipLines(s.text);
  return s.loaded && !s.saving && badIps(s.text).length === 0 && !(lines.length === s.saved.length && lines.every((l, i) => l === s.saved[i]));
};

export function ipReducer(s: IpState, a: IpAction): IpState {
  switch (a.type) {
    case "load":
      return s.saving || ipDirty(s) ? s : ipInit(a.ips);
    case "edit":
      return s.saving || !s.loaded ? s : { ...s, text: a.text };
    case "cancel":
      return s.saving ? s : { ...s, text: ipText(s.saved) };
    case "save":
      return canSubmitIps(s) ? { ...s, saving: true } : s;
    case "saved":
      return ipInit(ipLines(s.text));
    case "failed":
      return { ...s, text: ipText(s.saved), saving: false };
  }
}

export const ipPayload = (s: IpState) => ({ blockedIps: ipLines(s.text) });

export const ipAsk = (ips: string[]): Ask => ({
  title: "Block by IP?",
  text: ips.length
    ? `Visitors from ${ips.join(", ")} will not be able to see your profile or posts.`
    : "No IP address will be blocked.",
  ok: "Save",
});


export const NONE: NewWriteBinding = { unbind: () => {} };

export function bindBlockByCountry({ doc, data, locked, unlocked }: NewWriteEnv): NewWriteBinding {
  const picker = countryPicker(doc, !locked);
  if (!picker) return NONE;
  const countryList = () => countriesOf(data().countries);
  let cs = countryInit(blockedOf(data().settings));
  const draw = () => {
    const list = countryList();
    drawCountries(doc, cs.picked, (c) => countryName(list, c));
    picker.save.disabled = !canSubmitCountries(cs);
    if (picker.input.value !== cs.search) picker.input.value = cs.search;
  };
  const dispatch = (a: CountryAction) => {
    cs = countryReducer(cs, a);
    draw();
  };
  const open = (again: boolean) => {
    if (!unlocked(picker.box)) return;
    if (again) closeMenu(doc);
    const shown = filterCountries(countryList(), cs.search);
    const options = shown.length
      ? shown.map((c) => ({ value: c.code, label: `${cs.picked.includes(c.code) ? "✓ " : ""}${c.name}` }))
      : [{ value: "", label: "No data available", disabled: "No country matches" }];
    const menu = showMenu(doc, picker.box, [{ name: "countries", radio: false, options }], (_g, code) => dispatch({ type: "toggle", code }));
    if (menu) menu.style.cssText += ";max-height:320px;overflow-y:auto";
  };
  const save = async () => {
    if (picker.save.disabled) return;
    const h = unlocked(picker.save);
    if (!h) return;
    const list = countryList();
    if (!(await ofConfirm(doc, countryAsk(cs.picked.map((c) => countryName(list, c)))))) return;
    dispatch({ type: "save" });
    if (!cs.saving) return;
    h.send({ method: "PUT", path: BLOCKED_COUNTRIES, body: countryPayload(cs) }).then(
      () => {
        dispatch({ type: "saved" });
        void toast(doc, SAVED_TOAST);
      },
      (e) => {
        dispatch({ type: "failed" });
        note(doc, picker.save, `Could not save: ${message(e)}`, true);
      },
    );
  };
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Node;
    const chip = (t as Element).closest?.<HTMLElement>("[data-oi-country]");
    if (chip && picker.box.contains(chip)) {
      ev.preventDefault();
      if (unlocked(picker.box)) dispatch({ type: "toggle", code: chip.getAttribute("data-oi-country") ?? "" });
      return;
    }
    if (picker.box.contains(t)) return open(false);
    if (picker.save.contains(t)) {
      ev.preventDefault();
      void save();
    }
  };
  const onInput = (ev: Event) => {
    if (ev.target !== picker.input || locked) return;
    dispatch({ type: "search", text: picker.input.value });
    open(true);
  };
  const onRead = () => {
    const b = blockedOf(data().settings);
    if (b) dispatch({ type: "load", countries: b.countries, states: b.states });
  };
  draw();
  doc.addEventListener("click", onClick);
  doc.addEventListener("input", onInput);
  doc.addEventListener(SETTINGS_READ, onRead);
  return {
    unbind: () => {
      doc.removeEventListener("click", onClick);
      doc.removeEventListener("input", onInput);
      doc.removeEventListener(SETTINGS_READ, onRead);
      closeMenu(doc);
      countryPickerNotYet(picker);
    },
  };
}

export function bindBlockByIp({ doc, data, locked, unlocked }: NewWriteEnv): NewWriteBinding {
  const ipf = ipForm(doc, !locked);
  if (!ipf) return NONE;
  let is = ipInit(blockedOf(data().settings)?.ips ?? null);
  const draw = () => {
    if (ipf.field.value !== is.text) ipf.field.value = is.text;
    showIps(ipf.field);
    ipf.cancel.disabled = !canCancelIps(is);
    ipf.save.disabled = !canSubmitIps(is);
    const bad = badIps(is.text);
    const msg = ipf.field.closest(".v-input")?.querySelector<HTMLElement>(".v-messages__wrapper");
    if (msg) msg.textContent = bad.length ? `Not an IP address: ${bad.join(", ")}` : "";
    ipf.field.closest(".v-input")?.classList.toggle("error--text", bad.length > 0);
  };
  const dispatch = (a: IpAction) => {
    is = ipReducer(is, a);
    draw();
  };
  const save = async () => {
    if (ipf.save.disabled) return;
    const h = unlocked(ipf.save);
    if (!h) return;
    if (!(await ofConfirm(doc, ipAsk(ipLines(is.text))))) return;
    dispatch({ type: "save" });
    if (!is.saving) return;
    h.send({ method: "PUT", path: BLOCKED_IPS, body: ipPayload(is) }).then(
      () => {
        dispatch({ type: "saved" });
        void toast(doc, SAVED_TOAST);
      },
      (e) => {
        dispatch({ type: "failed" });
        note(doc, ipf.save, `Could not save: ${message(e)}`, true);
      },
    );
  };
  const onClick = (ev: MouseEvent) => {
    const t = ev.target as Node;
    if (ipf.field.contains(t)) return void unlocked(ipf.field);
    if (ipf.cancel.contains(t)) {
      ev.preventDefault();
      return dispatch({ type: "cancel" });
    }
    if (ipf.save.contains(t)) {
      ev.preventDefault();
      void save();
    }
  };
  const onInput = (ev: Event) => {
    if (ev.target === ipf.field && !locked) dispatch({ type: "edit", text: ipf.field.value });
  };
  const onRead = () => {
    const b = blockedOf(data().settings);
    if (b) dispatch({ type: "load", ips: b.ips });
  };
  draw();
  doc.addEventListener("click", onClick);
  doc.addEventListener("input", onInput);
  doc.addEventListener(SETTINGS_READ, onRead);
  return {
    unbind: () => {
      doc.removeEventListener("click", onClick);
      doc.removeEventListener("input", onInput);
      doc.removeEventListener(SETTINGS_READ, onRead);
      ipFormNotYet(ipf);
    },
  };
}
