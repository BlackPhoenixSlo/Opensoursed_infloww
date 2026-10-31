"use client";

import { useState } from "react";

/** The tag name modal's limit (#81). */
export const SCRIPT_TAG_MAX = 32;

/** The script editor's "Tags" (#74): several, "Select or create a tag". Enter or a comma adds the typed name; the
 *  list offers the Creator's existing tags. */
export function ScriptTagsField({
  tags, options, onChange,
}: {
  tags: string[];
  options: string[];
  onChange: (next: string[]) => void;
}) {
  const [text, setText] = useState("");
  const add = (raw: string) => {
    const name = raw.trim().slice(0, SCRIPT_TAG_MAX);
    if (name && !tags.includes(name)) onChange([...tags, name]);
    setText("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-border px-2 py-1 min-h-9">
      {tags.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded bg-bg-elev-1 px-1.5 py-0.5 text-xs">
          {t}
          <button
            type="button"
            aria-label={`Remove tag ${t}`}
            onClick={() => onChange(tags.filter((x) => x !== t))}
            className="text-fg-dim hover:text-fg"
          >
            ×
          </button>
        </span>
      ))}
      <input
        id="script-tags"
        type="text"
        list="script-tag-options"
        value={text}
        maxLength={SCRIPT_TAG_MAX}
        placeholder={tags.length ? "" : "Select or create a tag"}
        onChange={(e) => {
          const v = e.target.value;
          // Picking from the list fills the whole name at once: take it as chosen.
          if (options.includes(v)) add(v);
          else setText(v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add(text);
          } else if (e.key === "Backspace" && !text && tags.length) {
            onChange(tags.slice(0, -1));
          }
        }}
        onBlur={() => text.trim() && add(text)}
        className="flex-1 min-w-[8rem] bg-transparent text-sm outline-none"
      />
      <datalist id="script-tag-options">
        {options.filter((o) => !tags.includes(o)).map((o) => <option key={o} value={o} />)}
      </datalist>
    </div>
  );
}
