# Ultra black/red look

Type: prototype (owner: agent picks)
Status: resolved
Blocked by: none

What does the Ultra checkbox switch to — black + red "AI style" panel. Taste: variants, recommend, human picks.

## Answer

Owner (2026-11-13, rung 2): agent picks one look, owner asks for changes later, so there is no variant gate.

Pick, applied when the Ultra checkbox is on, scoped to the assistant panel only:
- near-black panel `#0b0b0d` with a 1px red border `#e11d2e` and a soft red outer glow;
- header "ULTRA" in red small-caps with a slow pulsing red dot while running;
- plan-card steps as a numbered list with red step numbers;
- the OK button solid red;
- running steps show a thin red progress line.

Done as tokens in the panel's own CSS module, not app-wide. Screenshot it on and off in both themes.
ASSUMPTION: these colours are taste, so cheap to change.
