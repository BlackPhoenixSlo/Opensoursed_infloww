# Phase 01 — Never-public gates for the Fansly mirror

**Objective.** Before any Fansly mirror file reaches private main, `app/public/fansly-mirror` (and its `.tmp` stage, and a bare file of that name) is a Never-public path: public replay skips it, the public whole-tree gate and the demo base check reject it, `check-public-export.sh` refuses it, AE still ships it, and a planted-file proof shows all of that.

## Problem Statement
The owner wants a full Fansly Manager like the OF one, built from a scrubbed copy of Fansly's own creator UI. That copy is Fansly's copyrighted CSS, fonts and markup. The OF mirror was meant to stay off the public repo (its NOTICE.md, `docs/OPEN_SOURCING.md`), but nothing enforced it, and its 397 files are on `public/main` and `twin/main` today (ticket 06, rung 1). A file that reaches public cannot be taken back out of its history. If the Fansly mirror lands on main the way the OF mirror did, the next public sync or deploy-all publishes it, and Twin and the demo inherit it from public.

## Solution
The Fansly mirror joins the one exclusion the gates actually enforce: the public and strip `NEVER_PATHS` list in the public-sync leak checker, beside `app/public/client-brand/`. Every public-bound path already reads that one list (replay, the whole-tree gate, deploy-all's gate and strip compare, the demo base check), so one entry covers public, app.inflowwww.com, the demo and Twin. AE keeps its own profile and gets the copy, as it gets the OF mirror. The older export check and the open-sourcing doc learn the new path, the generator's staging folder is ignored by git, deploy-all's checker self-test plants mirror files so a future loosening is caught, the demo base check reads its path list NUL-delimited so a non-ASCII name cannot slip past it, and the whole change merges as its own PR before any Phase 3 commit puts a mirror file on main (generating into the ignored stage locally before then is fine).

## User Stories
1. As the owner, I want `app/public/fansly-mirror/**` stripped by the leak checker's public profile, so that a public sync never copies a Fansly mirror page.
2. As the owner, I want the strip profile to strip it too, so that every tool that filters with the strip profile agrees with public.
3. As the owner, I want `app/public/fansly-mirror.tmp/**` (the generator's stage) stripped, so that a stage committed by mistake does not leak.
4. As the owner, I want a bare file named `app/public/fansly-mirror` stripped, so that the gate does not depend on the mirror being a folder.
5. As the owner, I want the AE profile to pass every Fansly mirror path, so that the AE site gets the Fansly Manager as it gets OF Manager.
6. As a public-sync operator, I want replay to print `skip (never public): app/public/fansly-mirror/...` for each mirror file in range, so that I can see it was held back, not lost.
7. As a public-sync or deploy-all operator, I want `leak-check.sh --tree` under the public profile to refuse a tree holding any Fansly mirror file under "never-public path", so that a tree that slipped past replay still cannot be pushed.
8. As a deploy-all operator, I want the demo stage to refuse a base carrying a Fansly mirror path, so that demo.inflowwww.com never serves it; the list comes from DEMO_HEAD's committed leak checker, and the base's paths reach it NUL-delimited so a Git-quoted name cannot dodge the anchored regex.
9. As the Twin maintainer, I want Twin never to receive the mirror, so that Twin stays clean; Twin merges only gated public commits, so the public gate is Twin's gate.
10. As a deploy-all operator, I want the "public strip is LOOSER than main's committed leak-check" compare to keep passing, so that this stricter list ships without a red; adding a path only grows "stripped by new only".
11. As a maintainer, I want the Fansly Manager's own code (route, nav, frame, page tables, generator script, tests) to keep shipping to public, so that the public app builds and shows a 404 frame instead of failing (edit 6, Phase 4's job to render).
12. As a maintainer, I want `scripts/check-public-export.sh` to refuse a checkout holding `app/public/fansly-mirror` or any sibling of that name (`.tmp`, `.old`, a bare file), with the filter-repo hint for that path, and its settings-check wrapper not to report clean over that refusal, so that the older manual export check agrees with the gate.
13. As a maintainer, I want `docs/OPEN_SOURCING.md` to name the Fansly path in the filter-repo scrub and say the enforced gate is `NEVER_PATHS`, covering the Fansly mirror only, so that the doc stops implying the OF mirror is enforced.
14. As a developer running the generator, I want `app/public/fansly-mirror.tmp/` git-ignored, so that `git add -A` mid-run cannot stage it.
15. As a checker maintainer, I want deploy-all's `selftest` to plant a Fansly mirror page and a stage file (public: caught; AE: allowed) and a Fansly Manager component (allowed on both), so that a later edit that drops or widens the entry turns the self-test red.
16. As the owner, I want this to merge as its own PR before any Phase 3 output reaches main, so that no window exists in which main holds mirror files and the gate does not.
17. As the owner, I want the OF mirror left exactly as it ships today in this Phase, so that the parked OF cleanup stays my decision (map "Needs the human").
18. As a reader of the ADRs, I want ADR-0067 to say the gate is built and to cite the Phase it landed in, so that the decision record matches the code.

## Implementation Decisions
- **Owns.** The public-sync leak checker (`leak-check.sh`), `scripts/check-public-export.sh` and one line of its wrapper `scripts/settings-check/export-check.sh`, the path-list pipe in `demo/deploy.sh` `stage()`, deploy-all's `dry-run.sh` self-test plants table, root `.gitignore`, `docs/OPEN_SOURCING.md`, ADR-0067's status line, and this spec's own wording. Nothing in `app/`, `service/` or `scripts/fansly-mirror*`.
- **Interfaces.** No CLI changes. `leak-check.sh --filter-paths` under `public` and `strip` prints `strip: <path>` on stderr for any path matching `^app/public/fansly-mirror` (case-insensitive, extended, like its siblings); `ae` passes it. `--tree`, `--diff` and range modes change only through that list. `check-public-export.sh TARGET` exits 1 with a "Fansly mirror present" section when the path exists in TARGET.
- **Schema.** None.
- **Contracts.** The never-public list is one regex variable read by four consumers; none gets its own copy (rung 1: `replay.sh:76-78`, `demo/deploy.sh:37-56` "one list, no copy here", `dry-run.sh:402-415`, `ae-deploy/SKILL.md:62` uses the AE profile). So public-sync's, deploy-all's and ae-deploy's SKILL.md need no edit — ticket 06's "which skills need the new path" is answered: only the leak checker. The entry form, decided in ticket 06 edit 1:

```
MIRROR_PATHS='(?ix) ^app/public/fansly-mirror'
public|strip) NEVER_PATHS="...|(?:$CLIENT_PATHS)|(?:$MIRROR_PATHS)|..."   # ae) unchanged
```

  No trailing slash on purpose: it also matches `fansly-mirror.tmp/` and a bare file. It also matches any future `app/public/fansly-mirror<anything>`; that is accepted, the name is ours.
- **Leak checker content rules.** The `$lock` skip (`leak-check.sh:97`, minified-CSS exemption naming `app/public/of-mirror/`) is not widened. Under public the path fails before content matters; under AE every rule `$lock` exempts is already `off` or `report` (`leak-check.sh:123-124`), so a `$lock` entry could never turn an AE red green. What can fail AE inside the mirror is the `secret` rule (`fail` under AE) and `DATA_PATHS` names (`.key`, `.pem`, `.db`, `_secret`, measured: AE `--filter-paths` strips `app/public/fansly-mirror/x.key`, passes `bundle.css`).
ASSUMPTION (rung 5): generated Fansly output trips neither; Phase 3 runs the AE `--tree` gate on its first generated tree, and a hit there is fixed in the generator's scrub or asset naming, never by widening `$lock`. Overturned if that run is red inside `app/public/fansly-mirror/`.
- **Export check.** The single `of-mirror` presence block becomes a loop over `$TARGET/app/public/of-mirror` and the glob `$TARGET/app/public/fansly-mirror*` (so `.tmp`, Phase 3's `.old` and a bare file count), each existing entry printing the same `── <name> mirror present ──` section and its own `git filter-repo --path app/public/<name> --invert-paths` hint (ticket 06 edit 2). It stays manual and unwired, as today; the doc says so. Its wrapper `scripts/settings-check/export-check.sh` counts a `mirror present` section as `THIS EFFORT` (`bad=1`): today it parses only `file:line:text` records, so one inherited content hit beside the refusal prints "clean for this effort's lines" and exits 0 (`export-check.sh:14-25`, codex measured).
- **Demo path input.** `demo/deploy.sh` `stage()` lists the base with `git -c core.quotePath=false ls-tree -r -z --name-only` and calls `--filter-paths -z`. Today it pipes newline `ls-tree` output (`demo/deploy.sh:52-53`), and Git quotes a non-ASCII name with a leading `"`, which the anchored `^app/public/...` never matches, while `git archive` still ships the file (codex measured the miss). The list is untouched; only its input form changes, as the whole-tree gate already does (`leak-check.sh:82-83`).
- **Replay input.** Unchanged. `replay.sh:74-81` has the same newline/quoted input, but a quoted path then reaches `git diff -- <quoted>` as a literal pathspec that matches nothing, so the file is dropped, not replayed, and the NUL-safe tree gate still runs. Story 6's skip line is therefore promised for ASCII names only.
ASSUMPTION (rung 4): replay stays as is because the miss fails closed and the fix would change replay for every path; overturned if a public sync ever needs a non-ASCII allowed path, then replay moves to `-z` too.
- **Own text.** Every public-bound file this Phase adds or edits (this spec, ADR-0067, `.gitignore`) passes `leak-check.sh --diff` under both `strip` and `public`. Measured on the draft: `strip` refused two lines (the caption-rule name in the content-rules bullet and the path-list variable name in Acceptance), `public` also refused the AE host name in story 5; all three are reworded, so the first public sync after the merge is not blocked by this spec.
- **Docs.** `docs/OPEN_SOURCING.md` (itself an ops path, never public): add `--path app/public/fansly-mirror` to the filter-repo line; rewrite the paragraph under it to cover both mirrors, state that the enforced gate is `NEVER_PATHS` and that it holds the Fansly mirror only, carry the literal sentence "The OF mirror is not enforced." and say it is on public today pending the owner, and that a public app shows Fansly Manager mirror routes as an iframe 404 (rung 2, OPEN_SOURCING.md:83-85 pattern).
- **Ignore.** Root `.gitignore` gains `app/public/fansly-mirror.tmp/` next to the other generated-stage entries (precedent `kvm8-shadow-test.html.tmp`).
ASSUMPTION (rung 4): the `.gitignore` line lands here, not with the generator in Phase 3, because it is a gate and costs nothing early; the NOTICE.md inside the mirror stays Phase 3's, since the generator writes it (ticket 06 edit 4). Overturned if Phase 3's spec also claims it; then whichever lands second drops its copy.
- **Self-test plants.** Rows added to deploy-all `dry-run.sh`'s `PLANTS` (format `path|content|public|ae`):

```
app/public/fansly-mirror/pages/home/index.html|<p>planted</p>|fail|allowed
app/public/fansly-mirror.tmp/pages/home/index.html|<p>planted</p>|fail|allowed
app/components/fansly-manager/PlantedMirrorFrame.tsx|export const P = 1;|allowed|allowed
```

  The third row is the first `allowed` public plant; the selftest's non-fail pass already handles it (it plants every non-`fail` row and wants base rc). The bare-file case cannot share a tree with the folder plant, so it is proved by the `--filter-paths` table in Acceptance only. Changing `dry-run.sh` changes the checker fingerprint, so the next deploy-all reruns the selftest instead of hitting its cache (rung 1: `checker_fp`, dry-run.sh:19).
- **ADR-0067.** Status flips to `**Status: accepted** (<merge date>, ... Phase 1; ticket 06)`: the plan reference corrects "Phase 4" to "Phase 1" and "nothing built yet" goes (precedent: ADR-0054/0055 flipped when built). Its body stays.
- **Order.** One PR, merged to main before any Phase 3 commit that adds a file under `app/public/fansly-mirror`. The leak checker is a shared file (other efforts edit `NEVER_PATHS`); the ticket rebases on main before merge and keeps the one-line entry.
- **OF mirror.** Untouched: no `^app/public/of-mirror` entry, no removal from public, no Twin change (owner 2026-11-26: don't push to public; parked in map "Needs the human").

## Testing Decisions
- **Seam 1 (main): `leak-check.sh --filter-paths`**, the one function every public-bound consumer calls. A path table piped in under each profile; external behaviour on both streams: stripped paths on stderr and the kept paths, in order, on stdout (a filter that dropped allowed paths would otherwise pass). The same table run through main's committed checker must strip none of the Fansly rows, which proves the table is sensitive to the new entry and is deploy-all's strip-compare in small (old strips nothing the new one does not). Covers stories 1-6, 8-11, 17.
- **Seam 2: `leak-check.sh --tree REV`** with `WT` pointed at a throwaway git repo holding one planted mirror page and one Fansly Manager lib file: public rc 1 with the page listed under "never-public path" and the lib file absent; AE rc 0 "clean". Covers story 7 end to end through the real gate (measured mechanics with `client-brand` on this branch: public rc 1 listing the planted file, AE rc 0).
- **Seam 3: `replay.sh --check BASE HEAD`** on an object-only commit (temp index plus `commit-tree`, as `dry-run.sh` selftest does) that adds a mirror page and a Fansly Manager file on top of local `main`. External behaviour = the `skip (never public):` lines. `--check` exits before staging (`replay.sh:132`), so it proves the skip, not the staged set; the kept half rests on replay staging exactly Seam 1's stdout (`replay.sh:76-81`).
Base is `main`, not this branch: this branch's strip patches do not apply (measured: `replay.sh --check HEAD~1 HEAD` dies on `docs/platform-recipe.md`; main cf115e665 carries the fix and `--check main main` runs clean).
ASSUMPTION (rung 5): no full replay into a throwaway public worktree, since it needs this branch's strip patches to apply; overturned if one becomes cheap, then it asserts `git -C $WT diff --cached --name-only`.
- **Seam 4: `check-public-export.sh TARGET`** on a throwaway git checkout, with and without the folder.
- **Seam 5: deploy-all `dry-run.sh selftest`** with the new plants. `selftest` itself does not fetch, but it needs a RUN folder holding a public worktree and `ae/sha.txt` from `gate` (`dry-run.sh:483`), and an AE base carrying the caption corpus, which `ae-snapshot.sh` builds only from a commit already on `origin/main` (`ae-snapshot.sh:16-17`). Before the merge none exists, so it is not part of this Phase's local Acceptance; it runs at the next deploy-all (fingerprint change forces it). Seam 2 is the same `--tree` mechanics on a planted tree, run locally.
- **Seam 6: `demo/deploy.sh --stage DIR`** with `DEMO_REPO` a throwaway repo (no `public` remote, so the fetch fails offline and it uses the local ref, `demo/deploy.sh:48`) whose commit holds the committed leak checker, a plain mirror page and a non-ASCII-named mirror file: refuses; with only the non-ASCII file left it still refuses, naming it (red before the `-z` change). A clean positive stage is not asserted: the throwaway repo lacks the product paths and `Landing.tsx` that `archive` and `overlay()` need, and the refusal runs before both. Covers story 8 through the real script.
- **Twin (story 9)** is not tested here: `twin.sh` merges only the pushed public commit, so it inherits the public gate by construction (`deploy-all/twin.sh:19-42`).
- Prior art: deploy-all `dry-run.sh` selftest `PLANTS` (CAUGHT/ALLOWED per profile); ticket 06's proof list. No unit-test framework covers these shell gates and none is added (rung 5).

## Acceptance
```sh
# run with bash (process substitution, here-strings); `!` is ignored by set -e, so negatives go through no()
set -eu
no() { if "$@"; then echo "unexpected match: $*" >&2; exit 1; fi; }
cd "$(git rev-parse --show-toplevel)"
LC=.claude/skills/public-sync/leak-check.sh
for f in "$LC" scripts/check-public-export.sh .claude/skills/deploy-all/dry-run.sh; do bash -n "$f"; done

# Seam 1: public and strip strip the mirror, its stage and a bare file; Fansly Manager code and the OF mirror pass; AE passes all
P='app/public/fansly-mirror/pages/home/index.html
app/public/fansly-mirror/NOTICE.md
app/public/fansly-mirror.tmp/pages/home/index.html
app/public/fansly-mirror.old/pages/home/index.html
app/public/fansly-mirror
app/lib/fansly-mirror-pages.ts
app/lib/fansly-mirror-build.ts
scripts/fansly-mirror.mjs
app/components/fansly-manager/FanslyMirrorFrame.tsx
app/public/of-mirror/pages/home/index.html'
WANT=$(printf 'strip: %s\n' app/public/fansly-mirror/pages/home/index.html app/public/fansly-mirror/NOTICE.md \
  app/public/fansly-mirror.tmp/pages/home/index.html app/public/fansly-mirror.old/pages/home/index.html \
  app/public/fansly-mirror | LC_ALL=C sort)
KEEP='app/lib/fansly-mirror-pages.ts
app/lib/fansly-mirror-build.ts
scripts/fansly-mirror.mjs
app/components/fansly-manager/FanslyMirrorFrame.tsx
app/public/of-mirror/pages/home/index.html'
for prof in public strip; do
  GOT=$(printf '%s\n' "$P" | LEAK_PROFILE=$prof "$LC" --filter-paths 2>&1 >/dev/null | LC_ALL=C sort)
  [ "$GOT" = "$WANT" ]
  [ "$(printf '%s\n' "$P" | LEAK_PROFILE=$prof "$LC" --filter-paths 2>/dev/null)" = "$KEEP" ]
done
OLD=$(mktemp); git show "main:$LC" > "$OLD"
no grep -q fansly-mirror <(printf '%s\n' "$P" | LEAK_PROFILE=public bash "$OLD" --filter-paths 2>&1 >/dev/null)
rm -f "$OLD"
[ -z "$(printf '%s\n' "$P" | LEAK_PROFILE=ae "$LC" --filter-paths 2>&1 >/dev/null)" ]
[ "$(printf '%s\n' "$P" | LEAK_PROFILE=ae "$LC" --filter-paths 2>/dev/null)" = "$P" ]

# Seam 2: whole-tree gate on a throwaway repo with a planted page
T=$(mktemp -d); O=$(mktemp)
git -C "$T" init -q
mkdir -p "$T/app/public/fansly-mirror/pages/home" "$T/app/lib"
echo '<p>planted</p>' > "$T/app/public/fansly-mirror/pages/home/index.html"
echo 'export const P = [];' > "$T/app/lib/fansly-mirror-pages.ts"
git -C "$T" add -A
git -C "$T" -c user.name=t -c user.email=t@users.noreply.github.com commit -qm plant
rc=0; WT="$T" LEAK_PROFILE=public nice -n 10 "$LC" --tree HEAD > "$O" 2>&1 || rc=$?
[ "$rc" = 1 ]
grep -qx -- '-- never-public path --' "$O"
grep -qx '   app/public/fansly-mirror/pages/home/index.html' "$O"
no grep -q fansly-mirror-pages "$O"
WT="$T" LEAK_PROFILE=ae nice -n 10 "$LC" --tree HEAD | grep -q '^clean (ae)'
rm -rf "$T" "$O"

# Seam 3: replay skips the planted page as never public, keeps the Fansly Manager file
I=$(mktemp); B=$(git rev-parse main)
GIT_INDEX_FILE=$I git read-tree "$B"
blob=$(printf '<p>planted</p>\n' | git hash-object -w --stdin)
GIT_INDEX_FILE=$I git update-index --add \
  --cacheinfo "100644,$blob,app/public/fansly-mirror/pages/home/index.html" \
  --cacheinfo "100644,$blob,app/components/fansly-manager/PlantedMirrorFrame.tsx"
C=$(git commit-tree "$(GIT_INDEX_FILE=$I git write-tree)" -p "$B" -m "plant (object only)")
rm -f "$I"
R=$(nice -n 10 .claude/skills/public-sync/replay.sh --check "$B" "$C" 2>&1)
printf '%s\n' "$R" | grep -qx 'skip (never public): app/public/fansly-mirror/pages/home/index.html'
no grep -q 'skip (never public): app/components/fansly-manager/' <<<"$R"

# Seam 4: export check refuses the folder, passes without it
E=$(mktemp -d); git -C "$E" init -q
mkdir -p "$E/app/public/fansly-mirror"; echo x > "$E/app/public/fansly-mirror/x.html"
rc=0; X=$(scripts/check-public-export.sh "$E" 2>&1) || rc=$?
[ "$rc" = 1 ]; printf '%s\n' "$X" | grep -q 'app/public/fansly-mirror'
printf '%s\n' "$X" | grep -qF 'git filter-repo --path app/public/fansly-mirror --invert-paths'
rm -rf "$E/app/public/fansly-mirror"; mkdir -p "$E/app/public/fansly-mirror.tmp"; echo x > "$E/app/public/fansly-mirror.tmp/x.html"
rc=0; X=$(scripts/check-public-export.sh "$E" 2>&1) || rc=$?
[ "$rc" = 1 ]; printf '%s\n' "$X" | grep -qF -- '--path app/public/fansly-mirror.tmp'
rm -rf "$E/app/public/fansly-mirror.tmp"; scripts/check-public-export.sh "$E" | grep -q '^clean'
rm -rf "$E"
grep -q 'mirror present' scripts/settings-check/export-check.sh

# Seam 6: demo stage refuses a base with a mirror page or a non-ASCII-named mirror file (refusal comes before archive)
DR=$(mktemp -d); git -C "$DR" init -q
mkdir -p "$DR/.claude/skills/public-sync" "$DR/app/public/fansly-mirror/fonts" "$DR/app/public/fansly-mirror/pages/home"
cp "$LC" "$DR/.claude/skills/public-sync/leak-check.sh"
echo '<p>planted</p>' > "$DR/app/public/fansly-mirror/pages/home/index.html"
echo x > "$DR/app/public/fansly-mirror/fonts/$(printf 'caf\303\251').woff2"
git -C "$DR" add -A; git -C "$DR" -c user.name=t -c user.email=t@users.noreply.github.com commit -qm plant
S1=$(mktemp -d)/s; rc=0; X=$(DEMO_REPO="$DR" DEMO_BASE=HEAD DEMO_HEAD=HEAD demo/deploy.sh --stage "$S1" 2>&1) || rc=$?
[ "$rc" = 1 ]; printf '%s\n' "$X" | grep -q 'carries never-public'
git -C "$DR" rm -rq app/public/fansly-mirror/pages; git -C "$DR" -c user.name=t -c user.email=t@users.noreply.github.com commit -qm font-only
S2=$(mktemp -d)/s; rc=0; X=$(DEMO_REPO="$DR" DEMO_BASE=HEAD DEMO_HEAD=HEAD demo/deploy.sh --stage "$S2" 2>&1) || rc=$?
[ "$rc" = 1 ]; printf '%s\n' "$X" | grep -q 'app/public/fansly-mirror/fonts/caf'
rm -rf "$DR" "$(dirname "$S1")" "$(dirname "$S2")"

# Docs, ignore, plants, ADR
grep -q -- '--path app/public/fansly-mirror' docs/OPEN_SOURCING.md
grep -q 'NEVER_PATHS' docs/OPEN_SOURCING.md
grep -qF 'The OF mirror is not enforced.' docs/OPEN_SOURCING.md
git check-ignore -q app/public/fansly-mirror.tmp/pages/home/index.html
no git check-ignore -q app/public/fansly-mirror/pages/home/index.html
grep -q '^app/public/fansly-mirror/pages/home/index.html|.*|fail|allowed$' .claude/skills/deploy-all/dry-run.sh
grep -q '^app/public/fansly-mirror.tmp/pages/home/index.html|.*|fail|allowed$' .claude/skills/deploy-all/dry-run.sh
grep -q '^app/components/fansly-manager/PlantedMirrorFrame.tsx|.*|allowed|allowed$' .claude/skills/deploy-all/dry-run.sh
A67=docs/adr/0067-fansly-mirror-is-a-never-public-path-unlike-of-mirror-today.md
grep -q '^\*\*Status: accepted\*\* (20[0-9-]*,.*Phase 1' "$A67"
no grep -qE 'Phase 4|nothing built yet' <(sed -n 3p "$A67")

# This Phase's public-bound text passes both content scans
for prof in strip public; do
  git diff -U0 --no-color main HEAD -- .gitignore "$A67" docs/spec/phase-01-fansly-mirror-never-public.md | LEAK_PROFILE=$prof "$LC" --diff >/dev/null
done

# OF mirror unchanged in this Phase
no grep -q of-mirror <(sed -n "/^FOCUS_/,/^esac/p" "$LC")
# manual: next deploy-all run (needs init's fetch, out of this run's floor) -> `dry-run.sh selftest RUN` shows the three new plants CAUGHT/ALLOWED, `selftest rc=0`, and strip-compare "stripped by old only" empty.
```

## Depends on
None. Phase 3 (generator) depends on this Phase being merged to main first; Phase 4's public-404 behaviour relies on it.

## Out of Scope
- OF mirror cleanup (`^app/public/of-mirror` in `NEVER_PATHS`, removing its 397 files from public and Twin, rewriting public history): parked for the owner (map "Needs the human"; owner 2026-11-26 "don't push to public").
- Wiring `check-public-export.sh` into public-sync or deploy-all: the leak checker already gates every public path; a second gate is YAGNI (rung 5).
- Twin-local commits or a landing deploy that carry the copy: neither generates it (ticket 06 review, partial accept).
- The generator's NOTICE.md and stage-then-swap: Phase 3 (ticket 06 edit 4, ticket 03 (c)).
- Fansly tests reading page files only inside `it.skipIf(!existsSync(dir))` bodies, route/nav/identity tests on fixtures: Phase 3/4 (ticket 06 edit 5); listed so they are not dropped.
- Public's missing-page iframe 404 and `fansly_manager` off by default hiding nav: Phase 4 (ticket 06 edit 6).
- Running a public sync, deploy-all or AE deploy: the coordinator ships after the loop (map header).
- `docs/soak/01-setup-inventory.md`'s list of what the export check refuses: a dated inventory, not a live reference.
- Any capture, generator or app code: Phases 2-4.

## Further Notes
- Ticket 06's "which skills/scripts need the new path" is settled by observation: only `leak-check.sh`; public-sync, deploy-all and ae-deploy consume its list (rung 1, cited above).
ASSUMPTION (rung 3): the variable is named `MIRROR_PATHS` (ticket 06 edit 1) though it holds only the Fansly mirror; overturned if the owner adds the OF mirror, which would then join it.
ASSUMPTION (rung 5): Seam 3 plants on local `main`, not this branch, because this branch's strip patches do not apply; overturned once the branch is rebased past cf115e665, after which `HEAD` works as base too.
ASSUMPTION (rung 4): the deploy-all selftest is not run in this Phase (it needs a gated RUN folder and an AE snapshot of a commit on `origin/main`, neither of which exists before the merge); overturned if `ae-snapshot.sh` gains a local-commit mode, then it joins Acceptance.

## Review
codex (gpt, high effort, read-only sparse workspace), 2026-11-27. Blind call (B) then draft call (D).

- B1 path exclusion plus whole-tree rejection, client-brand precedent — **reject** (no change): it is already the Solution.
- B2 rely on the export check, filter-repo or Docker excludes — **reject**: the OF mirror is the measured counter-example (397 files on public); the spec already gates through `NEVER_PATHS`.
- B3 move the mirror out of `app/public` behind authenticated serving — **reject**: ticket 06 decided AE serves it like the OF mirror (constraint); raw static URLs on AE are accepted there.
- B4 Git-quoted non-ASCII names dodge the anchored regex in demo and replay — **partial**: demo fixed (Implementation "Demo path input", Seam 6; measured here: with the entry added, a base holding only `fonts/café.woff2` passed the filter and went on to `git archive`); replay left as is because the quoted pathspec matches nothing and the file is dropped, not shipped (Implementation "Replay input", ASSUMPTION).
- B5 a candidate that adds then deletes the mirror passes endpoint and tip checks — **reject**: replay builds one commit from the endpoint diff (`replay.sh:141-145`, applied once at :145), deploy-all's `commit` makes that single commit, and a hand-built multi-commit `PUBLIC_CANDIDATE` is equally open for every never-public path today; parity with `client-brand` is what the plan asked.
- B6 an inherited `LEAK_PROFILE=ae` loosens replay's filter; pin the committed gate — **reject**: the gate re-runs `--tree` with `LEAK_PROFILE=public` set explicitly (`dry-run.sh:231,402-403`), `init` refuses skill scripts that differ from `origin/main` (`dry-run.sh:240-241`), demo reads `DEMO_HEAD`'s committed checker (`demo/deploy.sh:50`).
- B7 export check: linked worktree exits 2, `.tmp` missed, wrapper can swallow — **partial**: `.tmp`/`.old`/bare file now covered by a glob and the wrapper counts a presence section (Implementation "Export check"); the linked-worktree exit is rejected, the tool targets export clones and Seam 4 uses `git init`.
- B8 define what may enter a build context (`.tmp`, raw captures in Docker) — **reject**: the stage is ignored, `ae-snapshot.sh` reads only committed trees (`ae-snapshot.sh:21-24`), AE may carry the mirror anyway, and public hosts build from the public repo, which never has it.
- B9 test through real commands with varied plants, demo stage, AE retention, and a mutation check — **partial**: Seam 6 (demo, non-ASCII plant), the main-checker sensitivity check in Seam 1, and the `.old` row added; AE retention is proved by Seam 2's AE `--tree` and Seam 1's AE stdout, not by `ae-snapshot.sh`, which needs a commit on `origin/main`.
- B10 falsifiers: raw mirror URL 200 on a public build; staged index contents — **partial**: the URL check is Phase 4 (Out of Scope); the staged-set point is folded into D3.
- D1 demo bypass on quoted paths — **accept**: same fix as B4.
- D2 this spec trips the content scan replay runs, blocking the next public sync — **accept**, reproduced: `strip --diff` refused two lines, `public --diff` three (ADR-0067 clean); reworded, and Acceptance now scans this Phase's public-bound text under both profiles (Implementation "Own text").
- D3 Acceptance passes while the filter drops allowed paths; `--check` exits before staging — **partial**: Seam 1 now asserts stdout equals the kept list under public and strip; full staging stays unasserted (Seam 3 ASSUMPTION), since replay stages exactly that stdout.
- D4 stories 8-10 and 15 have no executable check; selftest's fetch premise is false — **partial**: 8 accepted (Seam 6), 10 accepted (main-checker compare in Seam 1), 9 rejected (Twin merges only the pushed public commit, `twin.sh:19-42`), 15: premise corrected (selftest needs a gated RUN folder and an AE snapshot of an `origin/main` commit, `dry-run.sh:483`, `ae-snapshot.sh:16-17`), still post-merge.
- D5 history of a re-gated candidate — **reject**: as B5.
- D6 wrapper reports clean over a refusal; `.tmp` outside the loop; hint unasserted — **accept**: Implementation "Export check", Seam 4 asserts the hint and a `.tmp`-only refusal.
- D7 AE contract overstated; a `$lock` entry cannot fix an AE red — **accept**: `$lock` only exempts rules AE already has off or report (`leak-check.sh:123-124`); ASSUMPTION rewritten to put any AE hit on the generator.
- D8 Solution forbade writing mirror files before merge, beyond the plan; replay fixture needs a ref past cf115e665 — **accept** the wording (only a commit putting mirror files on main must wait); **reject** the fixture point, already the Seam 3 ASSUMPTION and `main` contains cf115e665.
- D9 docs and ADR greps pass with wrong text — **accept**: Acceptance greps the literal "The OF mirror is not enforced." and the ADR status line for an accepted date, Phase 1, and no Phase 4 or "nothing built yet".

### Six hats (plan review, 2026-11-27)
- Yellow, Phase 1 is cheap and guards the irreversible thing (Fansly's copyrighted files reaching public) — **accept**: no change; this is why it ships first.
- Blue / Reorder, merge Phase 1 now, before the Phase 2 gate, the tracer and the Phase 3+4 PR — **accept**: story 16 already orders it before any Phase 3 output; Depends on unchanged ("None").
- Green, cuts in Phases 2-4 — **accept** there; nothing in this Phase is cut (its stories are the gate itself).
