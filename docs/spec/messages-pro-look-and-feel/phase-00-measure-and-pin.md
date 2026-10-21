# Phase 00 — Measure and pin

**Objective.** One Compare page, `docs/screenshots/messages-pro-compare.md`, sets the Clone's Messages Pro shot beside ours, holds a Compare row for every item of Phases 1–5 (Region, the Clone's px, ours, the owning ticket, matched or not) and carries the Colour inventory that maps every colour token class and literal in Messages Pro's JSX to its Infloww palette value, with no change to code, the harness or its states.

## Problem Statement

A person who knows Infloww's Messages Pro opens ours and sees a different screen, but nothing in the repo lists what differs, by how many px, or which ticket fixes it. The parity doc (`docs/messages-pro-parity.md`) grades Regions in prose and never grades colour, because ADR-0001 kept our colours. ADR-0010 now makes the Infloww palette Messages Pro's default, and nobody has listed which colours Messages Pro paints today or what Infloww paints in the same places. Phases 1–5 can't say "matched" until each difference is written down with a number on both sides.

## Solution

The Phase writes one Markdown page. At the top it records the commit it measured and places `clone-messages-pro.png` and `messages-pro-desktop.png` side by side, both taken by the existing `scripts/ui-shots.sh` run with no new state. Under the shots, the Compare rows list every visible difference as one table row each. Each row has a stable ID that Phases 1–5 and their tickets cite, and the row turns from `differs` to `matched` when its ticket lands. The Colour inventory section follows. It lists each colour token class Messages Pro's JSX uses (`bg-accent`, `text-fg-dim`, `border-border`…) and each colour literal, says what each one paints, gives today's value and the Infloww value with its source, and names the colour Compare row it belongs to. The Phase changes no code.

## User Stories

1. As a reviewer, I want one page with the Clone's Messages Pro shot beside ours at 1440×900, so that I can see the screens side by side without running anything.
2. As a reviewer, I want the page to name the commit it measured, so that I know which code the "Ours" column describes.
3. As a reviewer, I want the page's shots to come from the existing harness with no new harness state, so that the plan's "no new state" decision holds and the shots are the ones the Visual loop already gates.
4. As a Phase 1–5 implementer, I want every item of my Phase to appear as a Compare row before I start, so that my ticket has a measured target.
5. As a Phase 1–5 implementer, I want each Compare row to have a stable ID (CO, SH, FL, CH, TH, CP plus a number), so that my ticket, my spec and my commit can cite the row.
6. As a Phase 1–5 implementer, I want each Compare row to give the Region, the Clone's px with its `messages.html:line`, our px with its source, the owning ticket and a status, so that "done" is a number I can check.
A row's Difference cell states the target (Infloww's layout) and today's state, in that order, so that no row can be read as asking to keep today's layout.

7. As a Phase 1 implementer, I want Compare rows CO1–CO7 for the accent, the outgoing bubble (blue: the plan's colour, which beats the capture's grey, see the Clone px rule), the incoming bubble (grey), the PPV card with its price line (grey), the shell (near-black), the divider and the text colours, so that Phase 1's "colour rows all read matched" Acceptance has rows to read.
8. As a Phase 1 implementer, I want row SH1 (target: at desktop width Messages Pro hides the Top bar, so the Window header's Creator tabs row is the first row; today the Top bar sits above it) and row SH2 (target: the sidebar toggle, clock and avatar sit at the Window header's right end; today they are in the Top bar), so that the shell change has measured targets.
9. As a Phase 2 implementer, I want Fan List rows FL1–FL8: the avatar at the left with the online dot and spend under it (FL1); name, verified badge and handle on one line (FL2); ✕ at the right (FL3); a one-line preview (FL4); time at the right (FL5); a muted bell on muted Fans (FL6); 96px rows (FL7); the unread and owe dots as left-edge markers at Infloww's size (FL8). That way each part of the row layout is measured on its own.
10. As a Phase 2 implementer, I want rows for the Fan List header's first row (Creator name left; gallery, search and "+" right, FL9) and its second row ("All inboxes", gear, "Newest first", sort and refresh, FL10), so that the header reorder has targets.
11. As a Phase 2 implementer, I want row FL11 for the Notifications toggle, marked `ours` because Infloww has no such switch, so that the plan item is on the page and nobody grades it against the Clone.
12. As a Phase 3 implementer, I want Chat header rows: line 1's left side with name, verified badge and edit pencil (CH1); line 1's right side with "Open in new tab", refresh and kebab (CH2); line 2 with status, star, bell, notes, pin, Gallery and Find (CH3); Inflowwww extras (trend, +, Persona ⓘ, All Models marker) moved into the kebab or the "+" overflow, where today they render inline (CH4); and the 44px flag-on shift going to 0 (CH5, measured with the Legacy flag on). That way the two-line header and the extras move each have a target.
13. As a Phase 4 implementer, I want Thread rows: the per-bubble action row with pin, reply, heart and translate, measured for size and spacing (TH1); its visibility, on hover at desktop and always on phone (TH2); date dividers (TH3); the incoming avatar at the left of each incoming group (TH4); the outgoing avatar at the right (TH5); and the "Jumping to latest…" pill against Infloww's chip (TH6).
14. As a Phase 5 implementer, I want Composer rows: row 1 with emoji and gear left, AI, Scripts and timer right (CP1); row 2's input and the "Press "/" + keyword to quickly search scripts" placeholder (CP2); row 3's icons left and Send right (CP3); the PPV button right of Scripts (CP4); the fourth row with the price field and free-preview notice (CP5); the "+" overflow opening on-screen at 390 (CP6); and the Fan insights slide-over fitting 390 (CP7, today 11px over). That way the three-row rebuild and both phone gaps have targets.
   Phase 4's Part C (bubble shape, run gap, time row under the run; its Gap rows T10–T12) takes the next free Thread IDs, TH7–TH9, each Difference cell starting "Part C:" and owned by the Part C ticket. If the human vetoes Part C, their Ticket cell reads `unowned` and they stay `differs` for Phase 6 to see.
15. As a reviewer, I want phone-only rows (TH2's phone half, CP6, CP7) measured at 390×844, with "Clone px" naming the viewport constraint because the Clone has no phone layout, so that the plan's 390 goal is measured too.
16. As a reviewer, I want visible differences outside Phases 1–5's items listed as extra Compare rows with ticket `unowned`, so that Phase 6's sign-off sees them rather than finding them later.
17. As a reviewer, I want the real Infloww captures to outrank the Clone, so that a row where the Clone is wrong (for example Infloww's own 96px rows) targets Infloww's real value. When a capture disagrees, the Clone px cell must say so with the capture's measured value.
18. As the project owner, I want no name or handle from the real captures written anywhere, and no capture copied into the repo, so that the floor on untrusted ground truth holds.
19. As a Phase 1 implementer, I want a Colour inventory row for every colour token class used in Messages Pro's JSX, with its opacity variants, Regions, what it paints, today's dark value and the Infloww value with its source, so that I can switch each use without hunting for it.
20. As a Phase 1 implementer, I want each colour literal (file:line) listed in the Colour inventory the same way, so that the few colours outside the token classes are not missed.
21. As a Phase 1 implementer, I want token classes whose role differs by element (for example `bg-accent` as an outgoing bubble against the Send button) split into one inventory line per role, so that one class can take two Infloww values where Infloww uses two.
22. As a Phase 1 implementer, I want colours with no Infloww counterpart (status colours, scrims, the per-Creator colour) marked "keep" with the reason, so that the inventory is complete without inventing Infloww values.
23. As a reviewer, I want each inventory line to name the colour Compare row (CO1–CO7) it belongs to, or `—` for "keep" lines, so that "CO rows matched" means every inventory line in them is switched.
24. As the project owner, I want this Phase to change nothing under `app/`, `scripts/` or `service/`, so that the plan's "No code change yet" holds and the measured commit is the code that runs.
25. As a reviewer, I want one runnable check that fails when a required Compare row is missing, a ticket cell names no issue file, a token class or literal is missing from the inventory, or code changed after the measured commit, so that the page can't silently go stale.

## Implementation Decisions

- **Owns.** The Compare page `docs/screenshots/messages-pro-compare.md`, a new file. The harness PNGs it embeds (`clone-messages-pro.png`, `messages-pro-desktop.png`, and the phone shots the 390 rows cite) are regenerated by one ordinary harness run and committed with the page, as the Visual loop already does. Nothing else.
- **Interfaces.** The Compare page is the interface. Phases 1–5 read it and flip row statuses; Phase 6 grades from it.
  - Header: a line `Measured at \`<full sha>\`` naming the commit whose code the "Ours" column measured (Legacy flag off unless a row says otherwise), a line naming the viewports (1440×900, and 390×844 for phone rows) and the font the harness shots render in (`'Sora Fallback'`, because the harness refuses the font download, `docs/ui-shots.md:73-75`), then an HTML `<table>` of two cells, `clone-messages-pro.png` left and `messages-pro-desktop.png` right, by relative path.
  - `## Compare rows`: one Markdown table with exactly seven columns, `ID | Region | Difference | Clone px | Ours | Ticket | Status`.
    - **ID** matches `[A-Z]{2}\d+`. The required IDs are fixed here: CO1–CO7, SH1–SH2, FL1–FL11, CH1–CH5, TH1–TH6, CP1–CP7 (User Stories 7–14 give each one's meaning). Extra differences take the next free number in their prefix.
    - **Region** is a glossary Region name. SH rows are Window header; CP7 is Fan insights.
    - **Clone px** is the Clone's value with its `ui-redesign/infloww-exact/messages.html:<line>` (or `messages.js:<line>`). When a capture disagrees, the cell adds "Capture: <value> (wins)". A phone row with no Clone counterpart gives the viewport constraint instead ("fits 390").
    - **A colour the plan names beats the capture.** The plan's binding decisions name five colours (blue accent, blue outgoing bubbles, grey incoming bubbles, grey PPV card, near-black shell; plan:26-27, :39). Where a capture paints one of those elements another colour, the plan wins (rung 2, a constraint): the target is the source that carries the plan's colour, and the cell adds "Capture: <value> (overridden by plan)" instead of "(wins)". The case in view is CO2: the Thread capture paints our outgoing bubble grey, the plan says blue, so CO2 targets the Clone's `.bubble.out` `var(--blue)`, `#4166f6` (`messages.html:13`, `:246`).
    - **Ours** is our value with its source: a key of the Geometry token module (`app/lib/messagesPro.ts`), a `file:line`, or a browser measurement naming the shot.
    - **Ticket** is the owning ticket's number from `.scratch/messages-pro-look-and-feel/issues/`. A non-required row may read `unowned`.
    - **Status** is `differs`, `matched` or `ours`. FL11 is `ours`. A row reads `matched` when ours equals the target to the CSS px (±1px, for subpixel rounding) and, for a colour, to the hex as rendered; anything else is `differs`.
    - **Named remainder.** A `differs` row whose owning Phase has landed names what is left in its Ours cell as `remaining: <n>px — <reason>` (a colour: `remaining: <hex> — <reason>`). The per-Phase Compare gates of Phases 2–5 (FL, CH, TH, CP rows) pass a row that is `matched` or carries that phrase; strict `matched` holds only for CO1–CO7 and SH1–SH2 (plan Phase 1's Acceptance, plan:43-44). This is the per-Phase form of Phase 6's partial rule (`phase-06-sign-off.md`, Partial rule), so a typography- or font-bound difference (the harness renders `'Sora Fallback'`) can be recorded honestly instead of blocking the Phase or being rubber-stamped.
  - `## Colour inventory`: a table with exactly eight columns, `Token class | Variants | Regions | Paints | Ours (dark) | Infloww value | Source | Compare row`.
    - **Token class** is the backticked base class without variant prefixes or opacity, so `` `bg-accent` `` covers `hover:bg-accent/15`. The opacity and state variants go in Variants.
    - **Paints** says what the class paints. A class that paints two things Infloww colours differently gets one line per role.
    - **Ours (dark)** is the `@theme` value in `app/app/globals.css`.
    - **Source** is where the Infloww value came from: a capture sample (named by the element sampled, never by text), an Infloww stylesheet selector or variable, or a Clone variable at `messages.html:<line>`.
    - **Infloww value** is a hex, or `keep` for a colour with no Infloww counterpart (the reason goes in Paints).
    - **Compare row** is CO1–CO7, or `—` for a "keep" line.
  - A `### Literals` sub-table, the last part of the inventory, lists each colour literal with exactly six columns, `Literal | Paints | Ours | Infloww value | Source | Compare row`, the Literal cell being `<basename>:<line>`. The literals today are the per-Creator fallback `#666` in FanList and three `rgba` drop shadows in VaultPicker.
- **Schema.** None: no tables or storage.
- **Contracts.** The Compare page format above is the contract. Phases 1–5 change only a row's Status, and its Ours cell to the new value; Phase 6 reads Status. The harness contract (`docs/ui-shots.md`, parent `docs/spec/phase-00-pop-out-window.md`) is unchanged: the harness neither reads nor writes the page, and only deletes its own `OUTPUTS` PNGs and report.
- **Measuring Messages Pro JSX for the inventory.** The scope is every non-test `.ts`/`.tsx` under `app/components/chat/` and `app/app/messages-pro/`. A colour token class is a match of the house colour-class pattern (`COLOUR_CLASS` in `app/lib/messagesPro.test.ts`: utility `bg|text|border|ring|fill|stroke|outline|shadow|inset-shadow|divide|placeholder|caret|decoration|from|via|to` + token `bg|fg|panel|muted|border|accent|ok|warn|err|pink|info|white|black|transparent|current` with its suffixes). A colour literal is a match of `COLOUR_LITERAL` on a line that is not a comment. A grep of this worktree finds 57 base classes and 4 literals. The Acceptance check recomputes both sets, so new ones fail it.
- **Measuring the Infloww values.** Ground truth goes in the plan's order: the two Messages Pro captures (the empty-state shot and the Thread shot with Fan insights open) first, then the Infloww stylesheet and the Clone's `:root` variables, then `docs/infloww-screens.md` §1.4. The captures are 2× (3024px wide for a 1512px window), so a capture px is halved. Colours are sampled with `python3 -I` and PIL on a plain fill (a bubble's body, a button's face, a divider), and only the hex is written. Nothing from `~/Downloads` is copied, and no text, name or handle from a capture is quoted.
- **Measuring ours.** From the committed shots and the Geometry token module, at the measured commit. Rows the shots can't show (hover, flag on, phone overflow) are measured in a browser on the harness's isolated localhost servers. The parity doc's existing measurements count (CH5's 44px and CP6's x −208 to 42 come from ticket 127; CP7's overhang from ticket 127's slide-over measure) when the measured commit hasn't changed that code since.
- **No code change.** Nothing under `app/`, `scripts/` or `service/` changes in this Phase. The harness gains no state, flag or output.
- **Untrusted input.** The captures and the Infloww stylesheet are read with Read, grep or `python3 -I` only, never executed, never committed. Any temporary crop or thumbnail goes under `/tmp` and is deleted after the measurement.

## Testing Decisions

- **One seam: the Compare page itself, checked by the Acceptance script.** It parses the page and asserts that every required ID is present with seven cells, every Status is one of the three words (FL11 `ours`), every Clone px cell cites the Clone, a capture or the 390 constraint, every Ours cell cites a source, the phone rows name 390, every required row's ticket names an existing issue file, both shots exist and are on the page, every token class and literal in Messages Pro's JSX has its own inventory line whose Infloww value is a hex or `keep` and whose Compare row is CO1–CO7 or `—`, and nothing under `app/`, `scripts/` or `service/` differs from the measured commit, tracked or untracked. It can't prove a measured number is right or that a row's text means what its Story says; the human's skim covers that. It tests the page's external promise (complete, owned, current) and not how it was written.
- No vitest file is added: a test under `app/lib/` is a code change, and the plan says "No code change yet" (rung 2). Phase 1's Acceptance can lift the same parse into `app/lib/messagesPro.test.ts` if it wants the colour rows checked in the suite.
- The harness run (`scripts/ui-shots.sh`, `ok=True` in `messages-pro-report.json`) is the visual seam; it already exists and gains nothing.
- Prior art: the parent Phase 6 Gap table (`docs/spec/phase-06-geometry-pass.md`), pinned in `app/lib/messagesPro.test.ts`, which also defines the colour-class and literal patterns reused here. The Settings measured gap table (`docs/spec/settings-tabs/phase-00-shell-tokens-blob.md`) sets the row-per-difference format with a source cited on both sides.

## Acceptance

```sh
P=docs/screenshots/messages-pro-compare.md
test -f "$P"
# The measured commit is a real commit, and no code changed after it (plan: "No code change yet").
SHA=$(sed -n 's/^Measured at `\([0-9a-f]\{40\}\)`.*/\1/p' "$P" | head -1); test -n "$SHA"
git cat-file -e "$SHA^{commit}"
git diff --quiet "$SHA" -- app scripts service
test -z "$(git status --porcelain --untracked-files=all -- app scripts service)"
# The harness gains no state: its OUTPUTS list is unchanged since the measured commit.
git diff --quiet "$SHA" -- scripts/ui-shots.sh docs/ui-shots.md
# Shots are current: one ordinary harness run passes (a worktree links the main checkout's venv first, docs/ui-shots.md "Worktrees").
test -x venv/bin/python || { ln -s "$(git worktree list | head -1 | awk '{print $1}')/venv" venv && LINKED=1; }
bash scripts/ui-shots.sh; rc=$?; [ -n "$LINKED" ] && rm venv; test $rc -eq 0
python3 -I -c 'import json,sys; sys.exit(0 if json.load(open("docs/screenshots/messages-pro-report.json"))["ok"] is True else 1)'
# Page completeness: required Compare rows, owning tickets, both shots, full Colour inventory.
python3 -I - "$P" <<'PY'
import re, sys, glob, os
page = open(sys.argv[1]).read()
need = ("CO1 CO2 CO3 CO4 CO5 CO6 CO7 SH1 SH2 FL1 FL2 FL3 FL4 FL5 FL6 FL7 FL8 FL9 FL10 FL11 "
        "CH1 CH2 CH3 CH4 CH5 TH1 TH2 TH3 TH4 TH5 TH6 CP1 CP2 CP3 CP4 CP5 CP6 CP7").split()
rows = {}
for line in page.splitlines():
    c = [x.strip() for x in line.strip().strip("|").split("|")]
    if line.startswith("|") and re.fullmatch(r"[A-Z]{2}\d+", c[0]):
        assert len(c) == 7, f"{c[0]}: {len(c)} cells, want 7"
        rows[c[0]] = c
missing = [i for i in need if i not in rows]
assert not missing, f"Compare rows missing: {missing}"
for i, c in rows.items():
    assert c[6] in ("differs", "matched", "ours"), f"{i}: status {c[6]!r}"
    assert re.search(r"messages\.(html|js):\d+|Capture:|fits 390", c[3]), f"{i}: Clone px cites no source: {c[3]!r}"
    assert re.search(r"[\w.]+:\d+|messagesPro\.ts|\.png", c[4]), f"{i}: Ours cites no source: {c[4]!r}"
    t = c[5]
    if i in need or t != "unowned":
        assert re.fullmatch(r"\d+", t) and glob.glob(f".scratch/messages-pro-look-and-feel/issues/{t}-*.md"), f"{i}: ticket {t!r} has no issue file"
assert rows["FL11"][6] == "ours", "FL11 must read ours"
for i in ("TH2", "CP6", "CP7"):
    assert "390" in " ".join(rows[i]), f"{i}: phone row does not name 390"
for img in ("clone-messages-pro.png", "messages-pro-desktop.png"):
    assert img in page and os.path.isfile(f"docs/screenshots/{img}"), f"{img} not on the page or not on disk"
inv = page.split("## Colour inventory", 1)
assert len(inv) == 2, "no Colour inventory section"
inv = inv[1]
files = [f for d in ("app/components/chat", "app/app/messages-pro") for f in glob.glob(d + "/**/*.ts*", recursive=True)
         if ".test." not in f and "TestHarness" not in f]
cls = re.compile(r"(?:^|[\"'` :])((?:bg|text|border|ring|fill|stroke|outline|shadow|inset-shadow|divide|placeholder|caret|decoration|from|via|to)-(?:bg|fg|panel|muted|border|accent|ok|warn|err|pink|info|white|black|transparent|current)(?:-[a-z0-9]+)*)")
lit = re.compile(r"#[0-9a-f]{3,8}(?![0-9a-z])|rgba?\(|hsla?\(|oklch\(", re.I)
want, lits = set(), []
for f in files:
    for n, line in enumerate(open(f), 1):
        want.update(cls.findall(line))
        if lit.search(line) and not line.lstrip().startswith(("//", "*", "/*")):
            lits.append(f"{os.path.basename(f)}:{n}")
main, _, litsec = inv.partition("### Literals")
def table(txt, n):
    out = []
    for line in txt.splitlines():
        if not line.startswith("|"):
            continue
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if set("".join(c)) <= set("-: ") or c[0] in ("Token class", "Literal"):
            continue
        assert len(c) == n, f"inventory line {c[0]!r}: {len(c)} cells, want {n}"
        assert re.fullmatch(r"#[0-9a-fA-F]{3,8}|keep", c[-3]), f"{c[0]}: Infloww value {c[-3]!r}"
        assert re.fullmatch(r"CO[1-7]|—", c[-1]), f"{c[0]}: Compare row {c[-1]!r}"
        assert (c[-3] == "keep") == (c[-1] == "—"), f"{c[0]}: keep and — go together"
        out.append(c[0])
    return out
inv_cls, inv_lit = table(main, 8), table(litsec, 6)
cls_cells, lit_cells = " ".join(inv_cls), " ".join(inv_lit).replace("`", "")
nocls = sorted(w for w in want if f"`{w}`" not in cls_cells)
nolit = [l for l in lits if l not in lit_cells.split()]
assert not nocls, f"token classes missing from the Colour inventory: {nocls}"
assert not nolit, f"literals missing from the Colour inventory: {nolit}"
print(f"compare page ok: {len(rows)} Compare rows, {len(want)} token classes, {len(lits)} literals")
PY
# Nothing from the captures is in the repo.
test -z "$(git ls-files docs/screenshots | grep -v -E '^docs/screenshots/((messages-pro|clone|app|phone|desktop|landing|settings)-|\.gitkeep$)' )"
# The colour check on the Geometry token module still passes (no colour entered tokens).
pnpm -C app exec vitest run lib/messagesPro.test.ts
.scratch/messages-pro-look-and-feel/suite.sh
# manual: the human skims the page and confirms no name or handle from the real captures appears in it.
```

## Depends on

- No Phase: Phase 0 runs first.
- Ticket files — the `.scratch/messages-pro-look-and-feel/issues/<n>-*.md` tickets the spec step cuts for Phases 1–5. The Ticket cells and the Acceptance's ticket check read them, so Phase 0's ticket is claimed after they exist (the directory is empty at spec time).
- Existing — `scripts/ui-shots.sh` and its committed shots, the Clone (`ui-redesign/infloww-exact/messages.html`/`messages.js`), the effort's `.scratch/messages-pro-look-and-feel/suite.sh`.

## Out of Scope

- A new harness state, flag or side-by-side output: the plan says the harness gains no new state.
- Any code, token or test change, including a vitest file that parses the page: "No code change yet" (plan). Phase 1 may add one.
- Changing a row to `matched` because of work in this Phase: only Phases 1–5 flip statuses.
- Light-theme Infloww values in the Colour inventory: the captures and the Clone are dark. What Messages Pro shows under the light theme is Phase 1's open question (ADR-0010), and Phase 1 reads the stylesheet's light values itself if it needs them.
- Colours used outside `app/components/chat/` and `app/app/messages-pro/` (the app shell, `components/ui/` primitives): the App accent stays outside Messages Pro (ADR-0010). The Top bar's colours stop mattering on desktop once SH1 hides it.
- Regrading `docs/messages-pro-parity.md`: Phase 6 does that, with this page as evidence.
- Gaps the parent effort closed or handed to the human that Phases 1–5 don't name: they appear only as `unowned` rows if they're visible, and are not re-ticketed.

## Further Notes

ASSUMPTION: the Colour inventory is a section of the Compare page, not a separate file; the plan names no file for it, and Phase 1's Acceptance reads the colour rows "on the compare page" (rung 5, smallest thing). Overturned if the human wants a separate inventory doc.
ASSUMPTION: the inventory's unit is the base token class (variants and opacity folded into one line, split by role where Infloww uses two colours), plus each literal by file:line. The literal-only reading of the plan's "every colour literal" would list only 4 entries, because Messages Pro paints with token classes (rung 3, the house `COLOUR_CLASS` pattern). Overturned if the human wants one line per variant.
ASSUMPTION: "Messages Pro JSX" is the non-test files under `app/components/chat/` and `app/app/messages-pro/` (rung 3, the parent effort's Owns paragraphs). Overturned if Phase 1 recolours a shared component outside them, which then joins the scope.
ASSUMPTION: the Compare row IDs (CO, SH, FL, CH, TH, CP and the numbering in User Stories 7–14) are coined here, because the other Phases are specced in parallel and cite rows by meaning (rung 6). Overturned if a Phase's spec splits or merges an item, in which case the row splits or merges and the Acceptance `need` list follows.
ASSUMPTION: when a capture and the Clone disagree, the Clone px cell carries the capture value marked "(wins)" rather than adding an eighth column, which keeps the plan's column list (rung 5). Overturned if the human wants a separate Infloww column.
ASSUMPTION: the Infloww accent comes from a capture sample. The Infloww stylesheet's `--element-action-primary-emphasis-00` is orange (`#fe7d50` / `#f88056`, `common.css`), while the Clone's `--blue` is `#4166f6` (`ui-redesign/infloww-exact/messages.html` `:root`) and the captures show a blue Online Fans button. The plan's binding "blue accent" and its ground-truth order put the capture first (rung 2 for the ranking; that the orange token is not Messages Pro's accent is inferred). Overturned if the human points at a stylesheet variable that holds Messages Pro's blue.
ASSUMPTION: colours with no Infloww counterpart (ok, warn, err, info, pink status colours, black and white scrims, the per-Creator colour) are listed as "keep" with Compare row `—`, not given invented Infloww values (rung 4, reversible). Overturned if a capture shows Infloww painting the same element, in which case that line maps to the sampled value.
ASSUMPTION: the Ticket cell names one ticket number from `.scratch/messages-pro-look-and-feel/issues/`, and non-required differences may read `unowned` for Phase 6 (rung 3, the parity doc's "owner" practice). Overturned if the coordinator cuts tickets after Phase 0 runs, in which case required rows carry their Phase label and the ticket check is relaxed.
ASSUMPTION: CO2's target is the Clone's `#4166f6` because the plan names outgoing bubbles blue and the Clone's `.bubble.out` is the only in-repo source painting them blue; the Thread capture's grey is noted "(overridden by plan)". The ranking (plan beats capture) is rung 2; picking the Clone's hex as "the plan's blue" is rung 3. Overturned if the human says the plan's "blue" was written from the Clone in error and Infloww's real outgoing bubble is the capture's grey, in which case CO2 targets the capture's hex and Phase 1's palette changes one value.
ASSUMPTION: the per-Phase gates accept a named remainder (`remaining: <n>px — <reason>`) for FL, CH, TH and CP rows, and only CO1–CO7 and SH1–SH2 must read `matched` (rung 2 for the CO rows, plan:44; rung 5 for the rest, the plan asking only that sign-off "names the remaining px difference", plan:85). Overturned if the human wants every row strictly `matched` before its Phase signs off.
ASSUMPTION: "matched" means equal to the target within ±1 CSS px and, for colour, the same hex as rendered; the plan names no tolerance (rung 4, a tight rule is easier to loosen than a loose one to tighten). Overturned if the human names a tolerance.
ASSUMPTION: the inventory carries no use-count column; Phase 1 needs each class's role and value, not how often it appears (rung 5). Overturned if Phase 1's spec asks for counts.
ASSUMPTION: the Acceptance's "nothing from the captures is in the repo" line checks that `docs/screenshots/` holds only harness-named files; it can't prove a capture's content is absent, so the manual skim stays (rung 5). Overturned by a stronger check the human names.

## Review

codex, 2026-10-15 (blind call B, draft call D).

- B1 reject — selector-level geometry and computed colours as a new harness output: the plan says the harness gains no new state (`docs/plans/messages-pro-look-and-feel.md:29-30`); the spec already lets rows the shots can't show be measured in a browser on the harness's localhost servers.
- B2 reject — screenshot overlays or image diffs: they need masking and stable fonts, and the harness refuses the font download (`docs/ui-shots.md:73-75`); a new diff output is new harness state.
- B3 accept (already the decision) — real captures outrank the Clone (`docs/plans/messages-pro-look-and-feel.md:9-15`); Story 17 and the "Capture: <value> (wins)" cell already do this.
- B4 accept — no pass rule for "matched": Status now defines matched as ±1 CSS px and the same rendered hex, flagged ASSUMPTION.
- B5 reject — which states are pinned: the spec measures hover, flag-on and phone rows in a browser and puts light theme Out of Scope per ADR-0010 (`docs/adr/0010-…:5-7`).
- B6 accept (already the decision) — a literal-only inventory misses the token classes; the spec inventories classes and literals, including the `#666` fallback in FanList.
- B7 reject — phone parity can't be measured against Infloww: Story 15 already grades phone rows by the viewport constraint ("fits 390"), not against the Clone.
- B8 partial — provenance and font: Source cells already name the capture element or stylesheet selector; the header now also records the viewports and the `'Sora Fallback'` font. No per-row Clone revision, since the Clone is pinned by the measured sha.
- B9 reject — test at the rendered browser output: that is the harness's job (`ok=True`, kept in the Acceptance); Phase 0's deliverable is a document, so its seam is the page check.
- B10 reject — ADR-0010's "layout already matched" premise contradicts the parity table's `partial` grades: Phases 2–5 exist for those layout gaps, and Phase 0 lists them. The ADR's premise is not this Phase's to re-open (rung 2).
- B11 reject — "all seven PNGs are absent": an artifact of the sparse review workspace; `git ls-files docs/screenshots` lists `clone-messages-pro.png`, `messages-pro-desktop.png` and the phone shots.
- B12 reject — Clone vs capture disagreement falsifies the Clone: the spec already treats the Clone as second to the captures (Story 17).
- D1 partial — SH1 read as keeping the Top bar: the row text described today's state, not a target. Story 8 now gives target then today, and a new rule says every Difference cell states the target first.
- D2 partial — CH4 read as keeping extras inline: same cause as D1; Story 12 now states the target (extras move into the kebab or "+" overflow, plan Phase 3) and CH5 the shift going to 0.
- D3 accept — "Depends on: None" was false: it now names the ticket files (the directory is empty at spec time) and the existing harness, Clone and suite.
- D4 partial — the inventory goes past "literals": rejected for token classes, since Messages Pro paints through classes and 4 literals can't back the CO rows Phase 1's Acceptance reads (`docs/plans/messages-pro-look-and-feel.md:43-44`). Accepted for the use-count column, which is dropped (YAGNI, flagged ASSUMPTION).
- D5 accept — the page check took any non-empty cell: Clone px must now cite `messages.html|js:<line>`, `Capture:` or `fits 390`, Ours must cite a `file:line`, `messagesPro.ts` or a `.png`, FL11 must read `ours`, and both shots must exist on disk. Whether a number is right stays with the human skim, now stated in Testing Decisions.
- D6 accept — the colour check matched a class anywhere in the section: it now parses the inventory and Literals tables by column count, requires a hex or `keep` Infloww value and a CO1–CO7 or `—` Compare row (`keep` iff `—`), and looks up each class and literal in its first column only.
- D7 accept — `git diff` misses untracked files: added `git status --porcelain --untracked-files=all -- app scripts service` must be empty (`app/.next` is git-ignored, so the harness build doesn't trip it).
- D8 partial — Stories without a seam assertion: the phone rows must now name 390 (Story 15) and the inventory mappings are checked (Stories 19–23); the meaning of each row (Stories 7–14) and capture values (Story 17) can't be checked by a script and stay with the human skim.
- D9 reject — `suite.sh` missing: `.scratch/` is left out of the review workspace on purpose; `.scratch/messages-pro-look-and-feel/suite.sh` exists in this worktree. Now listed under Depends on.

### Six hats

Six-hats report, 2026-10-15 (`.scratch/messages-pro-look-and-feel/SIX-HATS.md`).

- White, CO2 blue vs grey: **accept**. The Clone px rule now says a colour the plan names beats the capture ("(overridden by plan)"), Story 7's CO2 says so, and CO2 targets `#4166f6` (`messages.html:246`), flagged ASSUMPTION.
- Green/Black, gate strictness: **accept**. New "Named remainder" contract: Phases 2–5 gates pass `matched` or `remaining: <n>px — <reason>`; strict `matched` only for CO1–CO7 and SH1–SH2 (plan:43-44). Flagged ASSUMPTION.
- White, Part C unconditional in Phase 6: **accept** (this spec's half). Part C's three differences become extra rows TH7–TH9, owned by the Part C ticket, `unowned` if vetoed; Phase 4's Part C block keys on that.
- Black, the `ui-shots.sh` pin fails after Phase 1: **partial**. The pin is right for Phase 0 ("no new state" at measure time); Phase 6 re-pins `Measured at` to the final commit before re-running this block (`phase-06-sign-off.md`, Re-pin), so no change here.
- Black, hover, flag-on and phone rows measured in one-off sessions: **partial**. Phase 1 (CO samples), Phase 4 (hover and focus checks) and Phase 5 (`phone-composer-overflow` flow) move most of them into the harness as checks on existing shots; CH5 stays a recorded browser read because a flag-on 1440 shot would be new harness state (plan:30).
- Red, the design is too heavy (38 rows, 57 classes, ±1px): **partial**. The rows and inventory stay (plan:33 "every item ... must appear here first", plan:34 "every colour literal"); the self-graded "matched" is softened by the named-remainder rule, and the browser-backed CO checks stay the strict gate.
- Yellow, stable row IDs: **accept** (no change), they are the decision.
