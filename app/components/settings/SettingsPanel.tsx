import type { ComponentProps, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import { ChevronLeft } from "lucide-react";

import { cn } from "@/lib/utils";
import { GateNoteText, RetryLoad, type GateNote } from "@/components/settings/StickySaveBar";
import { IF_BTN } from "@/components/settings/ifButton";
import { IfSelect } from "@/components/ui/infloww";

export { IF_BTN, IF_BTN_PRIMARY } from "@/components/settings/ifButton";

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

export function Field({ label, htmlFor, children }: { label: string; htmlFor?: string; children: ReactNode }) {
  return (
    <div className="mb-[var(--if-field-gap)]">
      <label htmlFor={htmlFor} className="block mb-[var(--if-label-gap)] text-[length:var(--if-fs)] text-[var(--if-fg-3)] [html[data-theme=light]_&]:text-[var(--if-fg-2)]">
        {label}
      </label>
      {children}
    </div>
  );
}

const FIELD = cn(
  "w-[var(--if-input-w)] max-w-full h-8 px-3 rounded-[var(--if-input-radius)] border border-[var(--if-line)]",
  "bg-[var(--if-bg)] text-[length:var(--if-fs)] text-[var(--if-fg)] outline-none focus:border-[var(--if-accent)]",
  "disabled:bg-[var(--if-input-disabled)] disabled:text-[var(--if-fg-3)] disabled:cursor-not-allowed",
);

export function FieldInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(FIELD, "read-only:bg-[var(--if-input-readonly)]", className)}
    />
  );
}

export function FieldTextarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(FIELD, "h-auto py-1.5 resize-none", className)} />;
}

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

export type CardBox = "bordered" | "filled";

const CARD_BOX: Record<CardBox, string> = {
  bordered: "p-6 rounded-[8px] border border-[var(--if-line)]",
  filled: "mt-4 px-4 py-3 rounded-[12px] bg-[var(--if-card-bg)]",
};

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

export function NotWired({ label }: { label: string }) {
  return (
    <button type="button" disabled title="not wired" className={IF_BTN}>
      {label}
    </button>
  );
}

export const RADIO = cn(
  "appearance-none shrink-0 w-4 h-4 rounded-full border border-[var(--if-line)] bg-[var(--if-bg)] cursor-pointer",
  "checked:border-[var(--if-accent)] checked:bg-[radial-gradient(var(--if-accent)_0_4px,transparent_4.5px)]",
);

export const TABLE_ROW = "border-b border-[var(--if-line)]";
export const TABLE_CELL = "h-12 px-[var(--if-row-px)] whitespace-nowrap";

export type TableColumn = string | { label: string; className?: string };

export function SettingsTable({ columns, small, children, "aria-label": ariaLabel }: {
  columns: readonly TableColumn[];
  small?: true;
  children: ReactNode;
  "aria-label"?: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table aria-label={ariaLabel} className={cn("w-full text-left text-[var(--if-fg)]", small ? "text-[length:var(--if-fs-table)]" : "text-[length:var(--if-fs)]")}>
        <thead>
          <tr className={cn(TABLE_ROW, "bg-[var(--if-accent-bg)] text-[var(--if-fg-3)]")}>
            {columns.map((c) => {
              const col = typeof c === "string" ? { label: c } : c;
              return <th key={col.label} className={cn(TABLE_CELL, "h-[46px] font-normal", col.className)}>{col.label}</th>;
            })}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function LoadError({ error }: { error: Error | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="mb-3 text-[length:var(--if-fs)] text-[var(--if-danger)]">
      Failed to load: {error.message}
    </p>
  );
}

const listOf = (names: readonly string[]) =>
  names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

export function NotAppliedYet({ fields, children }: { fields?: readonly string[]; children?: ReactNode }) {
  if (fields?.length === 0) return null;
  const text = fields
    ? `Saved for your organization; ${listOf(fields)} ${fields.length === 1 ? "is" : "are"} not applied yet.`
    : children ?? "Saved for your organization; not applied yet.";
  return (
    <p className="text-[length:var(--if-fs-sm)] text-[var(--if-fg-3)]">{text}</p>
  );
}

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
