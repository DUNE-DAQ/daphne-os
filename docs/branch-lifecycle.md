# Branch lifecycle and deprecation

Audit date: 2026-09-14. Scope: **DUNE-DAQ/daphne-os only**. Deprecation means
no new development or deployments from that branch; historical references
remain available. No branch or tag is deleted or rewritten by this change.

## Active development

| Branch | Audited tip | Status |
| --- | --- | --- |
| `develop` | `2d5b5cd00ce84d7197ebab4de9265992c0bd80dd` | Default integration branch |
| `fix/server-v05-register-coverage` | `03feac946c5ba5175f7c304044e619e3010352b7` | Active; 171 commits ahead of `develop`, not yet merged |

The [v0.6 checkpoint](releases/v0.6/README.md) belongs to the second branch.
Its deployed server source is `a23e5a9`, not the older server on `develop`.
Do not retire this feature branch until its work has been integrated and
verified. The counts above describe the snapshot before this documentation
change, not a promise that branch tips will stay fixed.

## Deprecated: fully merged historical server branches

Every tip below is an ancestor of both audited active tips. These **16**
branches contain no commits absent from `develop`; use the active OS tree
for development instead. Ancestry proves history inclusion, not that every
historical behavior remains enabled or qualified on hardware.

Names below have the prefix `archive/daphneZMQ/`.

| Historical branch | Tip |
| --- | --- |
| `bugfix/AlignmentFailure` | `90ed100` |
| `bugfix/HDMEZZ_I2C` | `35d2d56` |
| `bugfix/I2CMutex` | `f2f1e84` |
| `feature/BIAS_voltage_controller` | `9a5c3f9` |
| `feature/HDMezz_driver_improvements` | `12ebb94` |
| `feature/HDMezzanine_monitoring` | `6470725` |
| `feature/chunk_readout` | `f85446f` |
| `feature/improveOsc` | `dd4a7f8` |
| `feature/sof_spi_driver` | `b7c51cd` |
| `feature/unify-led-scan-control` | `adbe3e5` |
| `features/spybufferdump_speed_increase` | `329e3a8` |
| `main` | `dd4a7f8` |
| `marroyav/dual-gateware-abi-v2` | `77b39b7` |
| `marroyav/readers` | `f4117d2` |
| `release/dual-gateware-server-2026.08.31-rc1` | `77b39b7` |
| `server` | `4be8e3a` |

`feature/improveOsc` and `main` are exact aliases. The dual-gateware branch
and RC1 branch are also exact aliases. Their names are retained for provenance;
published release tags and assets are unchanged.

## Retained: historical branches with commits outside the active history

Do **not** classify these nine branches as fully merged or useless. Their
original commits are not ancestors of either audited active tip. Some features
may have been reimplemented, but that requires a separate code/behavior audit
before claiming equivalence. They remain historical references, not supported
deployment branches.

Names below also have the prefix `archive/daphneZMQ/`. The count is the number
of branch commits not reachable from either active tip, separately; the two
counts happen to match. Counts are not additive across overlapping branches.

| Historical branch | Tip | Commits outside each active tip |
| --- | --- | ---: |
| `feature/afe-delay-eye-sweep` | `3e4a867` | 19 |
| `feature/read_dead_time` | `c83d615` | 1 |
| `feature/slow-control-emulator` | `c262397` | 6 |
| `feature/spy-trigger-control` | `ffe3963` | 23 |
| `feature/spybuffer-deduplication` | `246a5a0` | 5 |
| `feature/spybuffer_guards` | `1e412c9` | 15 |
| `marroyav/ps-system-status-protobuf` | `6c8b044` | 1 |
| `marroyav/server_bringup_thresholds` | `aa2942a` | 3 |
| `marroyav/server_threshold_xc` | `851430c` | 1 |

## Other legacy branches

| Branch | Tip | Disposition |
| --- | --- | --- |
| `10g_update` | `8c4d524` | Legacy HDL tree; deprecated for OS development, retained with 6 commits outside each active tip |
| `feature/integrated_selftrigger` | `b9275f7` | Legacy HDL tree; deprecated for OS development, retained with 10 commits outside each active tip |
| `refactor/split-daphne-os` | `a065bba` | Retired migration branch; fully merged into `develop`, local branch only at audit time |

HDL development now belongs to
[daphne-firmware](https://github.com/DUNE-DAQ/daphne-firmware). This audit
does not establish equivalence with that repository or modify its branches.

## Repeat the check before removing any reference

Some clones fetch only `develop`; explicitly fetch all remote branch tips.
This updates local tracking references but changes no GitHub branches:

```bash
git fetch origin '+refs/heads/*:refs/remotes/origin/*'
git ls-remote --symref origin HEAD
git rev-list --left-right --count \
  origin/develop...origin/fix/server-v05-register-coverage
git branch -r --merged origin/develop

# Example: zero means this archived branch has no commits outside develop.
git rev-list --count \
  origin/develop..origin/archive/daphneZMQ/bugfix/AlignmentFailure
git merge-base --is-ancestor \
  origin/archive/daphneZMQ/bugfix/AlignmentFailure origin/develop
```

Before a separately approved branch-name removal, preserve its exact tip in a
non-conflicting archive tag, verify that tag on the remote, and recheck the
branch tip. Never move a published release tag or infer equivalence from a
branch name, age, matching commit subject, or successful compilation.
The original migration inventory remains in
[daphne-server-history.json](daphne-server-history.json).
