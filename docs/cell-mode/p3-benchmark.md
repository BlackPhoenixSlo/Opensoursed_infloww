# Phase 3 recovery benchmark — DRY RUN

> **DRY RUN** — container Boxes, FakeOF, fixed low load. These numbers check the tool and the path; they are not the Phase 3 benchmark (ticket 65 runs it on throwaway Boxes).

- Run: 2026-11-27 14:23Z · commit `64aeeb096ee5` · tool `deploy/fleet/benchmark.py`
- Boxes: oi52-box (throwaway list `benchmark-containers.toml`)
- Evidence: `/private/tmp/claude-501/-Users-founder--t3-worktrees-opensouce-infloww-private-feat-aso-63-recovery-be-890005e492acd85e/9907dda4-ea1e-487f-a5f9-509d8fa9d148/scratchpad/bench1`

| drill | exit | minutes |
|---|---|---|
| move | 0 | 7.7 |
| failover | 0 | 3.2 |
| control | 0 | 5.9 |
| witness | 0 | 1.1 |
| upgrade | 0 | 14.8 |

## Story 30

10 proved · 0 red · 6 not proved

| line | result | value / why | source |
|---|---|---|---|
| 10 moves: grey p95 ≤90 s | proved | p95 14.1 s over 10 timed moves (13.1, 11.1, 11.1, 14.1, 11.1, 11.1, 11, 11.1, 11.1, 11.1) | move |
| hashes 10/10 | proved | 11/11 finished moves: copy digest = hash digest | move journals |
| 0 lost, 0 duplicates | proved | lost 0 (byte-identical copies); duplicates 0 (source makes no FakeOF call after the epoch write) | move |
| one sibling Cell on the source Box stays live through each move | proved | s03 live while s02 moved 11×; grey p95 14.1 s | move/sibling.json (ticket 53) |
| busiest Box killed and back ≤10 min after the Fence | proved | 3 Cells restored in parallel; Fence confirmed → ready max 50.277 s (s02 49.893, s03 50.099, s04 50.277) | failover |
| 15 min after the failover: inbox p95 ≤1 s | not proved | held load waits for ticket 65's owner yes; container numbers would be the laptop's | — |
| CPU ≤70% | not proved | held load waits for ticket 65's owner yes; container numbers would be the laptop's | — |
| RAM ≥25% free | not proved | held load waits for ticket 65's owner yes; container numbers would be the laptop's | — |
| steal p95 <10% | not proved | held load waits for ticket 65's owner yes; container numbers would be the laptop's | — |
| disk free ≥30% + 2× largest DB through the 15 min | not proved | held load waits for ticket 65's owner yes; container numbers would be the laptop's | — |
| Control cell killed and back ≤10 min after the Fence | proved | Fence confirmed → ready 20.099 s; kill → ready 26.0 s; data Cell kept serving (26 pings) | control |
| Witness crashed after every move step, incl. after an external write and before its journal line | proved | 37 processes killed before/after each step; abort probes past the boundary refused | move |
| Witness crashed after every failover step | not proved | the container drill kills fleet.py only after `down`; per-step resume is test_failover pytest | — |
| a front Box killed through the public hostname | proved | public hostname answered 200 with one front Box killed | witness |
| dead Box paged at 2 min with the exact command, again at 15 min | proved | 7/7 pager checks (recording notifier only) | witness |
| N/N+1 smoke after each step | proved | 21/21 checks | upgrade |

## Timings: kill → page → operator start → Fence confirmed → ready → first good backup

**busiest Box (failover drill)**

| stage | at (s after kill) | since previous stage (s) | label | note |
|---|---|---|---|---|
| kill | 0.0 | — | measured |  |
| page | 120.0 | 120.0 | inferred | dead-Box rule fires at 2 min (witness drill, tick clock) |
| operator start | 1.9 | 1.9 | measured | the drill starts `fleet.py failover` at once: no human, no wait for the page |
| Fence confirmed | 9.4 | 7.5 | measured | Hostinger stub |
| ready | 59.7 | 50.3 | measured | slowest Cell s04; includes the drill's refusal rounds (hash, epoch, bucket, stale) before the accepted restore |
| first good backup | — | — | not proved | drills run no backup after ready; Cells cron backs up every 5 min (inferred ≤5 min + one run) |

**Control cell (control drill)**

| stage | at (s after kill) | since previous stage (s) | label | note |
|---|---|---|---|---|
| kill | 0.0 | — | measured |  |
| page | 120.0 | 120.0 | inferred | dead-Box rule fires at 2 min (witness drill, tick clock) |
| operator start | 0.8 | 0.8 | measured | the drill starts `fleet.py failover` at once: no human, no wait for the page |
| Fence confirmed | 5.9 | 5.1 | measured | Hostinger stub |
| ready | 26.0 | 20.1 | measured | Control cell, standin Readiness |
| first good backup | — | — | not proved | drills run no backup after ready; Cells cron backs up every 5 min (inferred ≤5 min + one run) |

## Data lost per class

| class | moves | busiest Box failover | Control failover |
|---|---|---|---|
| Own data | 0 (byte-identical: data/, service/, .env hashed) (measured) | 0 messages below the count read just before the kill across 3 Cells (s02 149→156, s03 137→142, s04 124→130); `--accept-stale` copy, writes between that read and the kill not counted (measured) | not proved: backup taken right before the kill; restored rows not compared |
| sessions | 0 (byte-identical: data/, service/, .env hashed) (measured) | not proved: restic small-file snapshot restored, not compared | not proved |
| media | 0 (byte-identical: data/, service/, .env hashed) (measured) | not proved: media snapshot restored, not compared | not proved |

## What this run does not prove

- scaled run: container Boxes on one laptop, FakeOF, fixed low load (the drills' own chatter loops)
- no held load: the 15 min at the Cell budget waits for ticket 65's owner yes (R5)
- Readiness is a standin that answers at once: real session login time is not in any ready number
- power Fence is the Hostinger stub: real stop/confirm latency is not measured
- one Docker host: CPU, RAM, steal and disk numbers would describe the laptop, not a Box
- Witness pager runs on a tick clock: page time is the rule, not a wall-clock delivery
- the operator is the drill: page → operator start is not a human reaction
- no WAN: WireGuard and front Boxes share one Docker network
- drill Boxes, not 8–11 Boxes: no busiest-of-many choice, no spare sizing under real DBs
