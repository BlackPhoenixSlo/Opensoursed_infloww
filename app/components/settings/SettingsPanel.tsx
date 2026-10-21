/**
 * The Panel parts every Settings tab is built from
 * (docs/spec/settings-tabs/phase-00-shell-tokens-blob.md, gap table rows 8-12):
 * Infloww's geometry through the `--if-*` tokens (globals.css, ADR-0009). No
 * hooks, so the server `[tab]` page can wrap its placeholder in a Panel.
 * Not wired and Not applied yet follow ADR-0008.
 */

import type { ComponentProps, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import { ChevronLeft } from "lucide-react";

import { cn } from "@/lib/utils";
import { GateNoteText, RetryLoad, type GateNote } from "@/components/settings/StickySaveBar";
import { IF_BTN } from "@/components/settings/ifButton";
import { IfSelect } from "@/components/ui/infloww";

export { IF_BTN, IF_BTN_PRIMARY } from "@/components/settings/ifButton";

/** A Panel: the 48px Panel header naming the tab (plus an `actions` slot on
 *  the right, and with `onBack` a 20px back chevron before the title) over a
 *  body with 24px padding that scrolls on its own (md and up). */
export function SettingsPanel({
  title,
  actions,
  onBack,
  children,
}: {
  title: string;
  actions?: ReactNode;
  onBack?: () => void;
  children: ReactNode;
}) {
  return (
    <div data-settings="panel" className="flex flex-col md:h-full">
      <div
        data-settings="panel-header"
        className="shrink-0 h-[var(--if-header-h)] md:mx-[var(--if-panel-pad)] flex items-center gap-3 border-b border-[var(--if-line)]"
      >
        {onBack && (
          <button
            type="button"
            aria-label="Back"
            onClick={onBack}
            className="-ml-1 grid w-6 h-6 shrink-0 place-items-center text-[var(--if-fg-2)] hover:text-[var(--if-accent)]"
          >
            <ChevronLeft aria-hidden size={20} />
          </button>
        )}
        <h2 className="text-[length:var(--if-fs-lg)] font-[var(--if-fw-title)] text-[var(--if-fg)] truncate">{title}</h2>
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </div>
      <div data-settings="panel-body" className="pt-3 md:flex-1 md:min-h-0 md:overflow-y-auto md:p-[var(--if-panel-pad)]">
        {children}
      </div>
    </div>
  );
}

/** A Panel section: a 14px/500 title (none when `title` is omitted), 16px under it, 40px after the section. */
export function Section({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="mb-[var(--if-section-gap)]">
      {title && (
        <h3 className="pb-[var(--if-section-title-pb)] text-[length:var(--if-fs)] font-[var(--if-fw-title)] text-[var(--if-fg)]">
          {title}
        </h3>
      )}
      {children}
    </section>
  );
}

/** A labelled field: 14px label in `--if-fg-3`, 8px above its control, 30px after the field. */
export function Field({ label, htmlFor, children }: { label: string; htmlFor?: string; children: ReactNode }) {
  return (
    <div className="mb-[var(--if-field-gap)]">
      <label htmlFor={htmlFor} className="block mb-[var(--if-label-gap)] text-[length:var(--if-fs)] text-[var(--if-fg-3)]">
        {label}
      </label>
      {children}
    </div>
  );
}

/** The 448px field control's classes, shared by FieldInput and FieldTextarea. */
const FIELD = cn(
  "w-[var(--if-input-w)] max-w-full h-8 px-3 rounded-[var(--if-input-radius)] border border-[var(--if-line)]",
  "bg-[var(--if-bg)] text-[length:var(--if-fs)] text-[var(--if-fg)] outline-none focus:border-[var(--if-accent)]",
  "disabled:bg-[var(--if-input-disabled)] disabled:text-[var(--if-fg-3)] disabled:cursor-not-allowed",
);

/** Infloww's 448px field input (32px high, ASSUMPTION in the spec); every input prop is forwarded. Read-only
 *  it is the bundle's `._disabled-input_rxwf7_242` (B-th `--if-input-readonly`, the same L1 border). */
export function FieldInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(FIELD, "read-only:bg-[var(--if-input-readonly)]", className)}
    />
  );
}

/** FieldInput's box as a textarea as tall as its `rows` (no auto-size, no resize handle); every textarea
 *  prop is forwarded. */
export function FieldTextarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(FIELD, "h-auto py-1.5 resize-none", className)} />;
}

/** Infloww's antd select (ticket 00's `IfSelect`: a combobox button over a listbox) at the 448px field width;
 *  `className` overrides the width. `searchable` puts a filter box over the list (the 400+ time zones). */
export function FieldSelect<T extends string>({
  options,
  className,
  ...props
}: {
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  id?: string;
  disabled?: boolean;
  searchable?: boolean;
  "aria-label"?: string;
  "aria-describedby"?: string;
  className?: string;
}) {
  return <IfSelect {...props} options={[...options]} className={cn("w-[var(--if-input-w)] max-w-full", className)} />;
}

/** A radiogroup named `name`, one native radio per option drawn as `RADIO`, each in a `rowClassName` label;
 *  `className` lays out the group. */
export function RadioGroup<T extends string>({
  name,
  value,
  options,
  onChange,
  rowClassName,
  className,
  "aria-label": ariaLabel,
}: {
  name: string;
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  rowClassName: string;
  className?: string;
  "aria-label": string;
}) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className={className}>
      {options.map((o) => (
        <label key={o.value} className={rowClassName}>
          <input
            type="radio"
            name={name}
            value={o.value}
            checked={value === o.value}
            onChange={() => onChange(o.value)}
            className={RADIO}
          />
          {o.label}
        </label>
      ))}
    </div>
  );
}

/** A 72px bordered row with a title, an optional description and a `Switch`.
 *  `notWired` makes the switch a disabled Not wired control (ADR-0008). */
export function ToggleRow(
  props: { title: string; description?: string } & (
    | { checked: boolean; onChange: (next: boolean) => void; notWired?: never }
    | { notWired: true; checked?: never; onChange?: never }
  ),
) {
  const { title, description } = props;
  return (
    <div className="h-[var(--if-toggle-h)] px-[var(--if-row-px)] mb-3 flex items-center gap-4 rounded-[var(--if-toggle-radius)] border border-[var(--if-line)]">
      <div className="min-w-0 flex-1">
        <div className="text-[length:var(--if-fs)] text-[var(--if-fg)]">{title}</div>
        {description && <div className="text-[length:var(--if-fs-sm)] text-[var(--if-fg-3)]">{description}</div>}
      </div>
      {props.notWired ? (
        <Switch checked={false} label={title} title="not wired" />
      ) : (
        <Switch checked={props.checked} label={title} onChange={props.onChange} />
      )}
    </div>
  );
}

/** Infloww's 44x22 antd switch named `label` (off rgba(255,255,255,.25), on #2d74ff, an 18px white knob,
 *  disabled at opacity .65: measured live). With no `onChange` it is disabled; `title` is its tooltip. */
export function Switch({
  checked,
  label,
  title,
  onChange,
}: {
  checked: boolean;
  label: string;
  title?: string;
  onChange?: (next: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={!onChange}
      title={title}
      onClick={onChange && (() => onChange(!checked))}
      className={cn(
        "relative shrink-0 w-11 h-[22px] rounded-full transition-colors disabled:opacity-[.65] disabled:cursor-not-allowed",
        checked ? "bg-[var(--if-switch-on)]" : "bg-[var(--if-switch-off)]",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "absolute top-0.5 left-0.5 w-[18px] h-[18px] rounded-full bg-white transition-transform",
          checked && "translate-x-[22px]",
        )}
      />
    </button>
  );
}

/** Which bundle card a `Card` draws. A closed set, like `GateNotePalette`, rather than a raw class string:
 *  - `"bordered"`: the `rxwf7` translation item, an `--if-line` bordered 8px box with 24px padding and no
 *    margin (the caller spaces its cards);
 *  - `"filled"`: the `1cat4` translation item, a 12px box on `--if-card-bg` with 12px 16px padding and its
 *    own 16px margin-top. */
export type CardBox = "bordered" | "filled";

const CARD_BOX: Record<CardBox, string> = {
  bordered: "p-6 rounded-[8px] border border-[var(--if-line)]",
  filled: "mt-4 px-4 py-3 rounded-[12px] bg-[var(--if-card-bg)]",
};

/** A Settings card in its `box` drawing. With a `title` it has a 14px/600 title row, 8px above its body:
 *  the optional `icon` 12px left of the title, the optional control on the right. An `icon` or a
 *  `control` needs a `title`. */
export function Card({
  box = "bordered",
  title,
  icon,
  control,
  children,
}: { box?: CardBox; children?: ReactNode } & (
  | { title: string; icon?: ReactNode; control?: ReactNode }
  | { title?: undefined; icon?: undefined; control?: undefined }
)) {
  return (
    <div className={CARD_BOX[box]}>
      {title && (
        <div className="mb-2 flex items-center justify-between gap-4 text-[length:var(--if-fs)] font-semibold text-[var(--if-fg)]">
          <span className="flex items-center gap-3">
            {icon}
            {title}
          </span>
          {control}
        </div>
      )}
      {children}
    </div>
  );
}

/** A control with no Relay endpoint behind it: Infloww's 32px default button (`IF_BTN`), disabled, titled
 *  "not wired", no handler, so it never stores anything or reports success (ADR-0008). */
export function NotWired({ label }: { label: string }) {
  return (
    <button type="button" disabled title="not wired" className={IF_BTN}>
      {label}
    </button>
  );
}

/** A native checkbox or radio drawn as antd's 16px radio: an L1 ring on B-nav, checked an M1 ring round an 8px
 *  M1 dot. */
export const RADIO = cn(
  "appearance-none shrink-0 w-4 h-4 rounded-full border border-[var(--if-line)] bg-[var(--if-bg)] cursor-pointer",
  "checked:border-[var(--if-accent)] checked:bg-[radial-gradient(var(--if-accent)_0_4px,transparent_4.5px)]",
);

/** A table row's rule and a cell's 48px box with the row's 16px inset, shared by every Panel table. */
export const TABLE_ROW = "border-b border-[var(--if-line)]";
export const TABLE_CELL = "h-12 px-[var(--if-row-px)] whitespace-nowrap";

/** A plain Panel table in its own horizontally scrolling box, so a Panel fits a 390px phone: antd's dark
 *  head (a 46px `--if-accent-bg` #353535 row of `--if-fg-3` column heads) over `--if-line` rules. `children` are the body rows. `small` draws the
 *  bundle's 13px billing-table cells (`._billing-table_6tj53_29 .ant-table-cell`). `aria-label` names the table
 *  when a Panel has more than one. */
export function SettingsTable({ columns, small, children, "aria-label": ariaLabel }: {
  columns: readonly string[];
  small?: true;
  children: ReactNode;
  "aria-label"?: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table aria-label={ariaLabel} className={cn("w-full text-left text-[var(--if-fg)]", small ? "text-[length:var(--if-fs-table)]" : "text-[length:var(--if-fs)]")}>
        <thead>
          <tr className={cn(TABLE_ROW, "bg-[var(--if-accent-bg)] text-[var(--if-fg-3)]")}>
            {columns.map((c) => (
              <th key={c} className={cn(TABLE_CELL, "h-[46px] font-normal")}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/** A failed roster load's one alert line, so an empty Employee list never reads as "no Employees". */
export function LoadError({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="mb-3 text-[length:var(--if-fs)] text-[var(--if-danger)]">
      Failed to load: {error.message}
    </p>
  );
}

/** "A", "A and B", "A, B and C". */
const listOf = (names: readonly string[]) =>
  names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

/** The ADR-0008 note, field-scoped (ADR-0012): `fields` names the Panel's fields still not applied, and an
 *  empty list renders nothing. With no `fields` it is the whole-Panel sentence, or a Panel's own wording as
 *  `children`. */
// ASSUMPTION: the field-scoped wording is "Saved for your organization; <A, B and C> is/are not applied yet."
// Rung 6: the spec names the fields, not the sentence. Overturned by Infloww or owner wording.
export function NotAppliedYet({ fields, children }: { fields?: readonly string[]; children?: ReactNode }) {
  if (fields?.length === 0) return null;
  const text = fields
    ? `Saved for your organization; ${listOf(fields)} ${fields.length === 1 ? "is" : "are"} not applied yet.`
    : children ?? "Saved for your organization; not applied yet.";
  return (
    <p className="text-[length:var(--if-fs-sm)] text-[var(--if-fg-3)]">{text}</p>
  );
}

/** A Blob tab's notes row: the Load gate's note when it has one, and Retry beside it once the load failed
 *  (settingsBlob.ts). With no note it renders nothing, so its `className` margin never pushes the first card down. */
export function BlobNotes({ note, q, className }: {
  note: GateNote | null | undefined;
  q: ComponentProps<typeof RetryLoad>["q"];
  className?: string;
}) {
  if (!note) return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-2", className)}>
      <GateNoteText note={note} palette="settings" />
      {note.failed && <RetryLoad q={q} />}
    </div>
  );
}
