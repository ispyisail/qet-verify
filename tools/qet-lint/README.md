# qet-lint

Dependency-free static checker for QElectroTech project (`.qet`) and element
(`.elmt`) files. No build, no launch, no GUI — pure file analysis, seconds
over the whole corpus.

```bash
python3 tools/qet-lint/__main__.py [--format text|json] \
    [--baseline FILE] [--write-baseline] [--include-info] PATHS...
```

`PATHS` may be files or directories (directories are walked for `*.qet` and
`*.elmt`). Exit code is 0 when there is nothing new to act on; any regression
against the baseline (or any finding when there is no baseline) exits 1.

## The rules

| ID | Check | Severity |
|---|---|---|
| P001 | any coordinate attribute is NaN or Inf | error |
| P002 | illegal XML 1.0 control character anywhere in a `.qet` | error |
| P003 | duplicate `uuid` value within one project | error |
| P004 | `%{key}` inside `<dynamic_elmt_text>` not in the registered-key allowlist | error |
| P005 | an electrical potential's members disagree on wire number or colour | warning |
| E001 | `.elmt` does not parse as XML (ElementTree) | error |
| E002 | illegal XML 1.0 control character in an `.elmt` | error |
| E003 | terminal names sort differently lexicographically than numerically | warning |
| E004 | two terminals in one element share the same non-empty name | warning |

P001 is not reimplemented here: it calls
`simulator/canon.py::nan_or_inf_violations()` and only attaches a source line
to each finding. P002 and E002 are the same byte scanner applied to the two
file kinds. P003 reuses the uuid extraction canonicalize() uses to build
`uuid_universe` (a `root.iter()` scan of `uuid` attributes) — see the note
below on why it is scoped to `<element>` uuids. P004 is the first stage-2
rule — origin and full derivation in
`DIAGNOSTIC-TOOLS-PLAN.md` §G1a — checking the same paired-invariant defect
class as P001-P003: a value written on one side of an interface with no
matching entry on the other.

### E003/E004 — terminal-name ordering and duplicates (DIAGNOSTIC-TOOLS-PLAN.md G4)

`naturalorder.py` ports `terminalNameLessThan()`, the comparator already
built and verified this session for QET's own source
(local branch `fix/terminal-sort-order`,
`sources/undocommand/linkelementcommand.cpp`) — three sort sites there
decide which master label lands on which terminal by comparing names as
plain strings, so a terminal numbered above 9 gets the wrong label. Ported
rather than re-derived, and re-verified after porting: same synthetic
cases, same strict-weak-ordering check over the same adversarial corpus (0
irreflexivity/asymmetry/transitivity violations).

**E003** flags an element once if `sorted(names)` disagrees with
`sorted(names, key=natural_sort_key)` — a broader check than the ad hoc
digit-only heuristic used to first measure this defect (94 of 6,918
elements): that heuristic only caught pure-digit names (`"2"` vs `"10"`)
and missed mixed alphanumeric ones (`"L2"` vs `"L10"`). The natural
comparator catches both. Full corpus, 2026-08-22: **114 elements**, 0.03s
per element average (7.8s total for 6,918 files). Proof fixture
(`wago_0287-0854-0000-0000.elmt`, 48 terminals up to 164) confirmed flagged.

**E004** flags a terminal name used more than once within one element
(excluding `name=""`, the normal unnamed state — 5,241 terminals
collection-wide have no name at all, and treating that as a duplicate would
be a false-positive flood). **Checked before writing the finding, not
assumed:** there is no `Element::terminal(const QString&)` or equivalent
name-keyed lookup anywhere in `sources/qetgraphicsitem/element.{h,cpp}`, so
a duplicate name is not the lookup hazard a duplicate uuid is. What *is*
verified: `naturalorder.terminal_name_less_than()` treats two
identically-named terminals as tied (neither compares less-than the
other), so which of the two receives which master label during the sort
becomes unspecified rather than something the element's own data
determines. Full corpus: **56 elements**, all hand-spot-checked against
the raw XML (distinct uuids, distinct positions, identical names — genuine,
not an XML-parsing artefact).

Both rules are `warning`, not `error` — flagging a real defect class, but
one that degrades gracefully (a plausible-looking wrong assignment) rather
than crashing, so it does not block the same way a P00x/E00x `error` does.

### What "illegal control character" covers (P002/E002)

XML 1.0 forbids U+0000–0008, U+000B, U+000C and U+000E–001F (U+0009 tab,
U+000A LF, U+000D CR are the only legal ASCII controls). The scanner flags
both ways one of those code points can reach the file:

1. a **raw control byte** (e.g. `0x00`), which ElementTree rejects as "not
   well-formed";
2. a **numeric character reference** (`&#11;` / `&#x0B;`), which ElementTree
   rejects as "reference to invalid character number" and which
   **segfaults Qt's `QDomDocument::setContent()`** rather than erroring.
   *(2026-09-23: not reproducible on Qt 6.10.2 -- `qelectrotech
   --check-elements` rejects both this entity form and the raw `0x0B`
   byte with an XML error and exit 1. The file in the collection now
   holds the raw byte, not the entity.)*

The brief describes P002's implementation as a "raw byte scan". A raw byte
scan alone cannot see form 2 (the file holds the six ASCII characters
`&#11;`, not a `0x0B` byte) — and form 2 is exactly what the criterion-1
fixture `xpx.elmt` contains. So the scanner handles both. That contrast —
"Python rejects it cleanly, Qt segfaults" — is the finding the fixture
exists to demonstrate.

## Hand-verification (brief §5: a rule nobody checked is worse than no rule)

Every rule that fires was checked by opening the file, not by trusting the
count.

### P001 — 1 instance (all of them)

`simulator/reports/findings/nan_coordinate_hang_grafcet.qet:93`:

```xml
<element freezeLabel="false" z="10" y="170" x="nan" prefix=""
        type="embed://import/grafcet2/etape.elmt" orientation="0"
        uuid="{12113ca8-85f5-4358-8548-fe386fa41760}">
```

A literal `x="nan"` on an `<element>`. Real. (This is the one project in the
known-bad set; the 23 example projects are clean, matching canon.py's note
that no real un-corrupted project should ever contain one.)

### P002 — 1 instance (all of them)

`simulator/reports/findings/nul_byte_segv_cablage.qet:616`: a raw `0x00` at
byte offset 51565. ElementTree rejects the file with "not well-formed
(invalid token): line 616, column 13", matching the reported line. Real.

### P003 — scoped to `<element>` uuids, 0 findings on the corpus

The brief points P003 at canonicalize's `uuid_universe`, which collects
**every** `uuid` attribute in the document. Counting occurrences over that
full universe and flagging any repeat produces a ~500-violation flood across
18 of the 23 known-good example projects. Three hand-verified samples of
that flood, all in files QET loads and renders correctly:

1. `perceuse.qet` — `<dynamic_elmt_text uuid="{9bfe240c-…}">` **×30**, all at
   the same relative position `x="-8" y="12"`: thirty instances of the same
   element sharing the element *definition's* text uuid. (QET's current
   source regenerates this uuid per instance — `element.cpp` "the uuid is
   the uuid of the description and not the uuid of instantiated dynamic text
   field" — but these files predate that fix.)
2. `perceuse.qet` — `<dynamic_text uuid="{d7645379-…}">` **×167** at many
   different positions: a folio's title-block texts, duplicated when the
   folio was duplicated.
3. `ShellyParts.qet` — `<terminal uuid="{455839e4-…}">` **×8** with different
   names (`SW`, `O1`, `L`, `GND`, `12V`, `O2`, …): terminal uuids copied
   across element instances.

None of these is "two objects sharing one identity"; they are QET's
copy-on-instantiate behaviour. Flagging them as `error` would be exactly the
false-positive flood §5 warns about, so P003 flags only the uuid that *is* a
strict identity — the `<element>` uuid, which QET resolves conductors
(via terminal uuid), cross-folio links (`link_uuid`) and undo/redo by, and
which is unique across all 23 example projects (0 duplicates). A duplicate
here is real corruption and will fail the gate.

*(Separately observed, not a rule: `cablage-eclairages_sikli-v5.qet` embeds
two `<definition>` blocks with the same `<uuid>` child but different content
— a genuine definition-uuid collision. Out of stage-1 scope; worth a stage-2
rule.)*

### P005 — potentials.py, and 2 real findings on the corpus

DIAGNOSTIC-TOOLS-PLAN.md G4.2's "potentials whose members disagree on
number or colour" bullet. Blocked for a while on the same thing the
neighbouring coincidence-check bullet was: QET has two format-selected,
mutually-exclusive-per-endpoint terminal addressing schemes (modern
`element1`/`element2` + a per-terminal-*definition* uuid; legacy plain
integers scoped to one diagram's own `Diagram::toXml()` id table — see
`potentials.py`'s module docstring for the full, source-verified
mechanism). Grouping conductors into "potentials" (connected components —
a bus/junction with several conductors on one terminal is one potential,
transitively) needs terminal *identity*, not position, so — unlike the
coincidence check — this rule resolves it directly rather than
delegating to QET's own loader: both schemes' identity keys are already
present verbatim on the `<conductor>` tag itself (no cross-referencing an
`.elmt` file needed), so a union-find over those keys is sufficient and
self-contained. A single conductor's two ends are resolved independently
(`conductor.cpp`'s `toXml()` decides per-end, so a conductor *can* mix
schemes) and legacy keys are scoped per-`<diagram>` (each folio's id table
is independent — sanity-checked with a real corpus grouping run first,
not assumed: 366 conductors → 256 potentials, largest 12, 202 singletons,
a plausible shape for a real wiring diagram before any rule logic was
written against it).

**2 findings on the real corpus**, both hand-verified, both look like
genuine issues rather than tool noise:

1. `Habitat-Unifilaire.qet:548` — 6 conductors meeting at one junction
   (terminal `"20"`), `num` values `{'10mm²', '10mm²k'}`: five say
   `"10mm²k"`, one says `"10mm²"`. `num` is being used here to carry a
   wire-gauge label, not a sequential number — same rule, different
   meaning of "number", still a genuine same-node disagreement.
2. `perceuse.qet:2920` — 8 conductors in one potential, all sharing
   `formula="%sequ_1"` (the same auto-numbering pool), 7 resolved to
   `num="45"`, **one still carries the raw, unresolved formula string
   `num="%sequ_1"`** instead of its resolved value. This looks like a real
   QET auto-numbering defect (one segment of a multi-conductor potential
   failing to resolve), not a data-authoring mistake — worth a `FINDINGS.md`
   entry of its own, separate from this tool.

**Conservative by design, checked not just asserted:** only 2+ *distinct
non-empty* values within a potential trigger a finding. A potential with
some blank members and one set value is not flagged — QET's own
numbering/colouring conventions may legitimately label only one
representative conductor per net, and this session did not verify that
either way, so treating "partially blank" as a defect would risk an
unchecked false-positive class. Real-data noise handled explicitly, not
discovered by a false positive: `num="&#xa;"` (a literal stored newline)
normalises to blank via `.strip()`; `" Noir"` vs `"Noir"` (real corpus
colour values with stray leading whitespace) normalise to the same value
and do not trigger a false "disagreement".

### E001 — 2 instances (all of them)

The brief says "~5 known-bad files, all in `<name lang="ca">`". The current
collection yields **2**, not 5; reported as-is, not tuned to a target.

1. `…/johnson_controls/dx/modules_extension/xpx.elmt:4` — `reference to
   invalid character number`, from `<name lang="ca">Unitat xPx &#11;erge</name>`.
2. `…/91_en_60617/en_60617_06/en_60617_06_04/en_60617_06_04_01.elmt:37` —
   `mismatched tag`, from a `<name lang="ca">` entry whose raw content is
   unclosed and embeds a `<name lang="cs">…</name>`.

Both are in `<name lang="ca">` translation content, as the brief describes;
there are just two of them now.

### E002 — 1 instance (all of them)

`xpx.elmt:4` — `&#11;` (U+000B) inside `<name lang="ca">`. Same byte the
E001 row above points at; E001 says "Python rejects it", E002 says "here is
the illegal character that made it so".

### P004 — `%{key}` resolves against `elementInfoKeys()`, and one namespace does not

QET substitutes `%{key}` inside a `<dynamic_elmt_text>` against
`QETInformation::elementInfoKeys()` (`sources/qetinformation.cpp:141-200`,
plus the parallel `DIA_*`/`PROJECT_*`/`COND_*` namespaces that merge into the
same substitution at render time). A key that is declared as a C++ constant
but never added to that list resolves to the **literal text** `%{void}` —
not a crash, not a warning, not a blank field: a wrong string a user has to
notice by eye.

**The allowlist (`infokeys.py`) is 83 keys**, extracted from
`qetinformation.h` and cross-checked against `elementInfoKeys()`'s body:
56 `ELMT_*`/`exclude_from_bom`, 13 `DIA_*`, 10 `PROJECT_*`, 6 `COND_*`,
1 (`version`). Five more `ELMT_*` constants are declared in the header but
**not** in that list — `plc_tc`, `plc_t1`, `plc_t2`, `plc_t3`, `plc_t4` —
and are deliberately excluded from the allowlist so P004 flags them.

**The scope decision that matters most for this rule's false-positive rate:**
`%{key}` is not one namespace. Inside a `<titleblocktemplate>`, `%{key}` is a
*custom title-block field* — open-ended per-project text, where an
unregistered key is normal (`QETProject::setTitleBlock`'s `apply` lambda does
`ctx.addValue(f.first, v)` for exactly this case; see the PR #710 review in
this repo's history). Measured across the 23 example projects: **178 of 180**
`%{key}` occurrences are inside a `titleblocktemplate`; only **2** are inside
a `dynamic_elmt_text` (both `%{description}`, a registered key). A rule that
checked both namespaces against the same allowlist would be a 178-instance
false-positive flood on the first run, over a corpus with **zero** real
violations. P004 computes byte spans for both block kinds and only checks
`%{key}` occurrences whose offset falls inside a `dynamic_elmt_text` span.

**Verified 0 findings** across the 23 example projects, the full 6,918-file
element collection (`.elmt` files never contain `<dynamic_elmt_text>` — it is
the placed-instance override, not part of an element definition, so this is
expected, not a coverage gap), and the two known-bad files in
`simulator/reports/findings/`. The proof fixture (a synthetic project with
`%{plc_tc}` in a dynamic text) is in the test suite, not committed as a
corpus file, because no shipped project currently uses a PLC terminal-count
field in a dynamic text — the defect is reachable, not yet observed in the
wild.

## Baseline

`--write-baseline` records `{path: {rule: count}}` (same shape as
`tests/determinism/baseline.json`, with a count instead of a bool):

```bash
python3 tools/qet-lint/__main__.py --baseline baseline.json --write-baseline \
    <qet-checkout>/examples \
    <qet-verify>/elements-10-electric/10_electric \
    simulator/reports/findings

python3 tools/qet-lint/__main__.py --baseline baseline.json \
    <qet-checkout>/examples \
    <qet-verify>/elements-10-electric/10_electric \
    simulator/reports/findings      # exit 0: no regressions
```

A run compares against the baseline and fails only on **regressions** — a
(file, rule) whose count went up or is brand new. The inverse is reported as
"vanished (fixed, or a rule stopped firing)" so a rule silently breaking is
visible, not hidden: if P001 fires N times yesterday and zero today, that
shows up as N vanished violations rather than a green run.

## Tests

```bash
python3 -m unittest discover -s tools/qet-lint/tests -v
```

Hermetic — the fixtures are synthetic, so the tests pass without the QET
element collection or example projects present.
