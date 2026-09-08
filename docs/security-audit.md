# Migration credential audit

Before importing daphneZMQ, all 245 commits reachable from its advertised
25 branches and 15 tags were scanned with Gitleaks 8.30.1. The scan used full
history and merge diffs, default credential rules, and additional checks for
short literal passwords, command-line SSH passwords, and Unix password hashes.
Commit and tag messages were scanned separately. The current firmware/OS
payload was also scanned, with archive traversal enabled.

Reports were fully redacted and kept outside the repositories in a private
directory. No credential values are reproduced in this document or CI output.
No project credential was detected by these scans. Automated scanning is not a
guarantee that every possible secret has been found.

## Reviewed public fixtures

Six historical findings were repeated occurrences of two unchanged files in
the bundled ZeroMQ 4.3.4 source. Both files were compared byte-for-byte with
their public upstream originals:

| File in the ZeroMQ tree | SHA-256 | Classification |
| --- | --- | --- |
| `doc/zmq_curve.7` | `82d8c7e238b0e820c1a7e16844074d073eafa633974ffd93cfa710a8fb5ad29a` | Published CURVE documentation examples |
| `tests/test_wss_transport.cpp` | `3cc4eec529ab24f12f83ea80b203f8a302557e768e13018fa894bbc0d128bfe1` | Public TLS test fixture |

The originals are in the [ZeroMQ 4.3.4 release](https://github.com/zeromq/libzmq/releases/tag/v4.3.4)
and [upstream transport test](https://github.com/zeromq/libzmq/blob/v4.3.4/tests/test_wss_transport.cpp).
These are not board, workstation, or service credentials. Never deploy the
public example keys as real credentials.

`scripts/security/verify_findings.py` permits only those exact file hashes,
rule IDs, and line locations. Changed content or any other finding blocks CI;
there is no blanket third-party exclusion. The original server history was
therefore preserved without redaction or hash rewriting.

## Ongoing safeguards

CI scans full reachable Git history, commit messages, and the current tree
using `.gitleaks.toml`, with all secret values redacted. Keep private reports,
board credentials, SSH material, and local environment files outside Git.
Some preserved upstream remote-helper examples accept credentials in command
arguments or environment variables. They are historical examples, not current
credential-handling guidance: do not put real credentials into shell history,
process arguments, checked-in scripts, or CI logs.
If an actual credential is discovered, stop publication and arrange revocation
or rotation; deleting it only from the current tree does not remove it from
history. Any history rewrite requires a separate coordinated decision.
