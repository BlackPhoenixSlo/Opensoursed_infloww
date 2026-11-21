"""Proof definitions, one module per Phase (`phase<N>.py`), plus fake-only `fixtures`; `ALL` maps proof id -> Proof.
`PENDING`: ids a Phase lists that have no definition yet (the driver parks them until their ticket adds them)."""
from proofs import fixtures, phase0, phase1, phase2, phase3, phase4, phase6

ALL = {p.id: p for p in (*phase0.PROOFS, *phase1.PROOFS, *phase2.PROOFS, *phase3.PROOFS, *phase3.WIRED_PROOFS,
                         *phase4.PROOFS, *phase6.PROOFS, *fixtures.PROOFS)}
PENDING = frozenset(phase6.IDS) - set(ALL)
