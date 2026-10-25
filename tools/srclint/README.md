# srclint

General source-level invariant checks for the QET C++/Qt source tree.
Corpus-free (unlike `tools/qet-lint`'s element-collection sweep or
`tools/crosspage`'s example-project sweep): srclint's rules read the source
tree / translation files directly and run in seconds. See
`DIAGNOSTIC-TOOLS-PLAN.md` G6 for the item this implements.

## Usage

```bash
python3 tools/srclint/srclint.py --qet-dir <qet-checkout>
python3 tools/srclint/srclint.py --qet-dir <qet-checkout> --gate   # exit 1 if any finding

# as scripts/gates.sh runs it: exit 1 only on a finding the baseline does not count
python3 tools/srclint/srclint.py --qet-dir <qet-checkout> \
    --baseline gate-reports/srclint-baseline.json --gate
# accept the current findings
python3 tools/srclint/srclint.py --qet-dir <qet-checkout> \
    --baseline gate-reports/srclint-baseline.json --write-baseline
```

`--qet-dir` is a QET checkout; `--sources` names its `sources/` tree
directly (default `sources/` relative to the current directory).

A baseline counts findings per key: `rule|file|source string` for R-C,
`rule|file|detail` for R-B. There are no line numbers in a key, so an
upstream edit that only moves lines does not fire the gate. A second copy
of a known string in the same file does, since it is counted. Findings
that disappear are listed as "gone" but never fail the run.

Without a baseline the gate could only say "some findings" and sat at
fail permanently; the old rule R-A went from 110 to 113 findings that way
without anyone noticing.

## Rules

### R-A — retired 2026-10-09

R-A flagged a `tr()` source *not* written in French, back when French was
the source language. PR #1390 (merged 2026-10-08) made English the source,
so on today's tree R-A would flag nearly every translated string. R-C
replaces it.

### R-B — context-less lambda `connect()` whose sender outlives the receiver

**Opt-in only: `--rule R-B`, not run by default.** Per
`DIAGNOSTIC-TOOLS-PLAN.md` G6.2 ("ships behind `--rule` until its flagged
set is under ~15") — measured at **59** on `qet-fix` @ `7307a59c1`, well
over that bar, so it stays out of the default run rather than quietly
lowering the bar to ship it anyway.

`connect(sender, &Sig::sig, [this]{...})` with no context object (a 4th
argument) is owned by the **sender**, not by `this`. If `this` — the
receiver the lambda actually touches — is destroyed before the sender,
the connection survives and later fires into freed memory. Proven, not
theoretical: `FINDINGS.md` F013 is exactly this shape
(`sources/TerminalStrip/ui/terminalstriptreedockwidget.cpp:67`), reproduced
as a heap-use-after-free under ASan on a standalone model with the
identical ownership graph.

**Pipeline:** `connectscan.py` extracts every `connect(...)` call from a
`.cpp` file with a small hand-rolled paren/comma scanner (a plain regex
can't reliably find a multi-line call's own closing paren, or split its
arguments, when the lambda body contains its own parens and commas —
verified against a real multi-line `projectview.cpp` connect() before
trusting it, see `tests/test_connectscan.py`). `rule_b_...` then keeps
only 3-argument calls whose 3rd argument is a lambda with `this` in its
explicit capture list (`[this]`, `[this, x]`, `[x, this]` — **not**
`[=]`/`[&]`'s implicit capture, a stated scope limit, not a silent miss).

**Measured before any heuristic:** 135 raw candidates across 32 files
(close to F013's own "133" — the small drift is source churn since that
scan, not a methodology difference; re-measured rather than trusted, same
as the old R-A count was).

**Sender-safety heuristic**, applied to bring 135 down to the real 59
(exclusions checked against real call sites, not assumed to work):

| Exclude | Why | Checked against |
|---|---|---|
| `sender == "this"` | can't outlive itself | (not in the plan's text — an obviously-correct addition found while measuring) |
| `sender` starts with `ui->` | owned by the `Ui::` struct, itself a member destroyed with the receiver | 7 `ui->...` senders in the raw set |
| `sender` (local or member) constructed via `new T(..., this, ...)` | Qt parenting bounds the sender's lifetime by the receiver's | `deti`/`group`/`slave`-style locals (21 of the raw 135) |

Everything else is flagged — **including** constructor-parameter members,
`QPointer<T>` members, and singleton accessors, exactly the cases the plan
calls real risk because none of them bound the sender's lifetime. A
connect to `&Class::destroyed` capturing `[this]` is **always** flagged at
`critical` regardless of the exclusions above (2 of the 59: F013's own
line, and `qetdiagrameditor.cpp:1586` — checked that the latter's sender,
`diagram_event`, is `new`'d parented to a `Diagram`, not `this`, so the
"parented to this" exclusion correctly does *not* apply there either).

**The two named fixtures, both verified:**
- **Must flag:** F013's exact line — flagged `critical`.
- **"Must not report" `sources/projectview.cpp:88,92`** (and `:86`,
  structurally identical, not named in F013 but the same shape) — **is
  flagged**, per the plan's own explicit fallback: *"If the heuristic
  flags those it is too coarse — but add a comment upstream, because that
  safety is an accident of the destructor, not a guard."* Added that
  comment upstream (branch `g6-srclint-upstream-comment` on `qet-fix`,
  doc-only, not opened as a PR) rather than trying to lexically encode
  "the destructor happens not to call `removeDiagram()`" as a fourth
  exclusion — that fact isn't derivable from `projectview.cpp`'s own text
  at all, and a heuristic that reached into `qetproject.cpp`'s destructor
  to special-case this one call site would be overfit to a single
  accident, not a real rule.

### R-C — a translatable string written in French

**Severity: warning. Runs by default.**

English is QET's `tr()` source language since PR #1390 (2026-10-08); French
is a translation in `lang/qet_fr.ts` like any other. A French source string
is a mistake: English users see French, and every translator is handed
French to translate.

R-C reads the source tree itself, so a new French string is flagged in the
change that adds it, before anyone runs `lupdate`. It takes:

- the string literal of `tr()`, `Class::tr()`, `QT_TR_NOOP()`, and the
  second argument of `translate()` / `QT_TRANSLATE_NOOP()`; adjacent
  literals (`"a" "b"`) are joined, comments are skipped;
- every `<string>` in a `.ui` file, except `notr="true"`.

A string counts as French if it has a word from `french_lexicon.json` (words
QET's French text uses and its English text never does, regenerated with
`qet-en-source lexicon`), an accented letter in a word English does not use,
or two French function words. French typography is deliberately **not** a
signal: about 400 of QET's English strings keep a space before ":" or use
« » ("Size :").

**Measured 2026-10-09:** upstream master after #1390 (`bdeef6d30`): 4,475
translatable strings read, **0 findings**. The tree just before #1390 merged
(`3420ce2ee^1`, French source): **3,535 findings**. The lexicon itself, on
master `ef795a21e`: of 63 French messages it was not learned from it misses
7 (five read as English — "Portrait", "Format :", "8 directions" — and two
use only unseen words), and flags none of the 3,737 English sources.

## Tests

```bash
cd tools/srclint && python3 -m unittest discover -s tests -v
```

40 hermetic tests (5 for R-C and its string extraction, 13 for the command
line and `--baseline`, 11 for `connectscan`'s call/capture extraction,
11 for R-B), no dependency on a checked-out `qet-fix` — each builds a
minimal fixture. R-C covers each kind of call, joined literals, comments,
escaped quotes, `.ui` strings with and without `notr`, and English with
French-style spacing that must not be flagged. With `looks_french()` forced
to return False, 8 of them fail.
