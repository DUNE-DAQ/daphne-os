# Deprecated: multi-board deployment handoff

This file described a proposed 200-board campaign and temporary development
branches. It is not an operator procedure and no longer represents the
repository's verified state.

The current firmware QA plan tests **one isolated board at a time**. This
repository provides one-board build, configuration, readback, deployment, and
evidence tools. It does not provide the campaign scheduler, authoritative
inventory, network admission, or multi-station coordination needed for a
large rollout.

Use these current documents instead:

- `build-manual.md` for a clean firmware build;
- `daphne-board-enrollment-runbook.md` for one-board identity and enrollment;
- `kria-board-identity-and-production-deployment.md` for deployment policy;
- `verification-status.md` for the checks that actually run today;
- the repository wiki for self-trigger, timing, and full-stream board tests.

Create a new reviewed campaign plan only after ownership of inventory,
networking, scheduling, and evidence storage is agreed. The original proposal
remains available in Git history.
