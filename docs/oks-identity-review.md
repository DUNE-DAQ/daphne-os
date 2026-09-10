# DAPHNE-015: review identity assignments from CERN OKS

Extractor source `30e8708`. This tool prepares a private review snapshot and
does not configure the board. The follow-up [private artifact and server
reporting](board-identity-verification.md) are now deployed and qualified.

The ONL source matching DAPHNE-15 is
`/nfs/home/marroyav/fddaq-v5.6.0-rc4-a9-1/ehn1-vst-daphne15`:

- `segments/pds-vst.data.xml`: application `test-daphne-app` → configuration
  `daphne_mezz` → map entry/board `daphne_mezz-daphne-15-conf`.
- `hw/pds-vst-connections.data.xml`: the application's connection links the
  board to Hermes sender `hds-daphne15`.
- `hw/senders/pds-vst-senders.data.xml`: the sender's streams agree with the
  board at **crate 4, slot 1, detector 8**; one interface supplies a MAC/IP
  assignment. Two stream IDs do not imply two separately assigned interfaces.

The plain `pds-dev/configs/vst` JSON files inspected identify board **61**.
The adjacent `np02` files identify boards **6/7/10**, not 15. A separate
`ehn1-daqconfigs-daphne15-vdcb` set has matching placement but is a different
source snapshot. Never select a source just because its folder says VST.

## Commands: review only

ONL's default `python3` is 3.6.8. Use installed **`python3.9`** for this tool
(Python 3.9 or newer required). From the source checkout:

```bash
umask 077
identity_review_dir=$(mktemp -d /nfs/home/marroyav/.daphne-identity-review.XXXXXXXX)
python3.9 daphne-server/scripts/extract_oks_identity.py \
  --root /nfs/home/marroyav/fddaq-v5.6.0-rc4-a9-1/ehn1-vst-daphne15 \
  --application-id test-daphne-app \
  --board-object-id daphne_mezz-daphne-15-conf \
  --verify-target NP04-DAPHNE-015.CERN.CH \
  --private-output "$identity_review_dir/identity.json"
```

Stdout is redacted; output JSON is exclusive-create, mode **0600**, and must
not be committed or published. Omit `--private-output` for a summary only.
Omit `--verify-target` for offline extraction without DNS queries. Nothing
opens SSH, MMIO, I2C or SPI, sends server commands, or edits MAC/IP/DHCP files.

The tool follows selected object relationships, checks explicit placement and
map-key consistency, validates address syntax and retains per-value object,
attribute, source-file and SHA-256 provenance. Missing/duplicate/ambiguous
selected fields or relationships are rejected. It reads only the three chosen
bounded files, not includes or schema defaults; it is **not a general OKS
resolver**. Input files are read sequentially, not a transactional database
snapshot. Hashes identify the consumed bytes, not an authenticated assignment
or proof that this configuration is currently active in run control.

XML entity declarations and alternate encodings are rejected. Use a maintained
Python/Expat runtime for ongoing operation; see [Python XML security](https://docs.python.org/3/library/xml.html#xml-security).

## Verified and still missing

All **74 tracked Python tests** pass locally, including **21 extractor tests**;
the same 21 tests pass on ONL's Python 3.9. Actual ONL extraction and optional
DNS comparison passed: the board management address and sender control host
resolve to the selected DAPHNE-015 target. DNS agreement is not live NIC
readback or cryptographic board identity. Imported assignments remain separate
from this host-timed observation.

Combined source revision:
`9dc51032d423353b06373bf65093c464e49c9ec2b0f16c3de5438437f9c86ff2`.
Private review file SHA-256:
`a97e7e734d6745ad212b0e9ebdfa1dac2f206394d68d63a2c4bf0449f7380fdb`.
Evidence: `completion-VEpMKkGG/identity-python-tests.txt` and
`identity-onl-review.txt`. No board runtime was restarted for this work.

Still unresolved: authoritative timing-endpoint assignment, management MAC
assignment, physical SFP-to-Hermes LinkId mapping, and additional link
assignments. `tp_conf` is trigger configuration, **not** a timing address.
Those fields remain null, not invented zero values. The validated private
artifact now supports protocol reporting of assigned versus observed identity;
there are no implicit network/configuration writes.
