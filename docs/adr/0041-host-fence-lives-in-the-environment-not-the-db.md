# The Host fence lives in the Relay's environment, never in its database

**Status: proposed** (2026-11-19, `goal_promo_preempt.txt` Phase 01; nothing built yet).

Test, shadow and demo stacks run on copied databases, and every Relay switch in `runtime_switches.py` reads DB override before env, so anything the database says travels with the copy: a copied DB with Keep running ticked would make real promos on the same OnlyFans session from a second host, and a Create reservation only fences Relays that share one DB. We decided the Host fence for automatic promo creates is read from the Relay's environment only: a host id (`PROMO_CREATE_HOST_ID`) set per box, never shared by a failover pair, compared with the host id stored when Keep running was ticked, and no `runtime_switches` row or other DB value can lift it. A missing or mismatched id means no automatic create, a visible warning on the Kept campaign, and an owner notice at boot when Kept campaigns exist; clearing the env value is the kill switch. On failover the human re-stamps the Kept campaigns on the box taking over (`promo_keep_restamp.py`, printed by `ae-fence clear`). We chose this because the environment is the one thing a database copy does not carry. The cost: every Deployment must set the id at deploy, or Keep running stays inert there (a post-deploy watch check, `promo_keep_fenced`, catches it); Kept campaigns ticked before the fence stay fenced until re-ticked. Going back means every target's deploy config changes again.
ASSUMPTION: an unset host id means no automatic create (rung 4, fail closed); overturned if the owner wants existing Deployments to keep creating before their deploy config sets it.
ASSUMPTION: the fence covers automatic creates only, not the Employee's manual Create promotion (rung 5); overturned if a copied stack's manual create must be fenced too.

## Considered Options

- **A `runtime_switches` kill switch.** Rejected: DB override wins and copies with the DB.
- **The container hostname.** Rejected: changes on every container recreate (inferred).
