# Plan: fleet live proofs (parked until needed)

Goal: prove `deploy/fleet/` (2–3 app copies per box, one agency ≤50 models per copy) on the spare KVM2 + live KVM4 with synthetic data, so buying a KVM8 later = follow written steps.

Status: plan only, nothing built. Full plan = [docs/plans/fleet-live-proofs/map.md](docs/plans/fleet-live-proofs/map.md) + tickets.

When needed:
1. Owner answers [08 owner inputs](docs/plans/fleet-live-proofs/issues/08-owner-inputs.md) (KVM2 address/ssh, fresh KVM4 go, window).
2. Build tickets 09 safety switches, 10 synthetic writer, 11 concurrent calibrate.
3. Run [06 proof runbook](docs/plans/fleet-live-proofs/issues/06-proof-runbook.md), then its KVM8 day one.

Out of scope: AWS, multi-core/Rust rewrite, cross-copy S4S (owner ruling 12).
