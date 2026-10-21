# Messages Pro takes Infloww's geometry and Inflowwww's colours

Superseded for Messages Pro by ADR 0010 (colours only; the Geometry rule stands).

The Clone this ADR cites was deleted in 2026-10 (cleanup Phase 2; tag `legacy-ui-final` keeps it). Its measured Geometry lives on in `app/lib/messagesPro.ts`.

Messages Pro is being rebuilt to match Infloww's Messages Pro element for element. The Clone (`ui-redesign/infloww-exact/messages.html`, `_shared/components.html`) carries both Infloww's layout and its sampled palette (`docs/infloww-screens.md` §1.4 [PAL]). We take only the Geometry from the Clone: widths, heights, paddings, radii, font and icon sizes, and element order. These numbers are measured into a single Messages Pro token module that every Messages Pro component reads, with no magic numbers in JSX. Every colour comes from the app's existing Tailwind tokens in `app/app/globals.css`, and §1.4 serves as reference only. A future reader comparing our screen with Infloww's will see the same layout in different colours, and that difference is deliberate.

ASSUMPTION: the reasons are inferred, because the plan states the rule without giving one. Geometry is what makes the screen work the way Infloww users expect. Colour is what keeps Messages Pro consistent with every other Inflowwww screen, and keeps the project at a distance from Infloww's visual identity (`docs/parody-voice.md`: "No Infloww logo or screenshots"). This is overturned if the human gives a different reason, which may change how a borderline value, such as a status colour, gets classified.

## Considered Options

- **Copy the Clone's palette too.** Rejected because Messages Pro would become the only screen in Infloww's colours.
- **Keep our current geometry and only relabel.** Rejected because it does not reach element-for-element parity, which is the goal.
