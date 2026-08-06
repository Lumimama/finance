# Month-End Close — Instrumented

**Live dashboard:** [close_dashboard.html](https://lumimama.github.io/finance/month-end-close/examples/close_dashboard.html)

Six monthly closes (Jul–Dec 2025) of a 13-task checklist with real
dependencies, owner roles, sign-off states, and a balance-sheet flux review
with materiality thresholds. The thesis: the close is a process with a
critical path, not a heroic sprint — and the dashboard names the current
bottleneck instead of celebrating average effort.

## The three findings the data was designed to contain

**1. The close got faster by attacking the path, not the people.**
Days-to-close falls from 8.9 to 6.9. The cause is one change: bank
reconciliation was automated in October (3.5 days of manual matching →
0.8). The critical path is *recomputed from the dependency graph every
month* — July's ran through bank rec; December's runs through revenue
cut-off review, which is therefore where the next day of improvement
lives. The dashboard says so explicitly and will keep saying so until it
moves.

**2. Flux review with teeth.** Any balance-sheet line moving more than
max($50K, 5%) month-over-month requires commentary. November ships one
breach — prepaid expenses, +31% — with the commentary missing, and the
engine refuses to certify that close until it's explained. The control
catching the gap is the demonstration. (December's lease-liability breach
is the GPU embedded lease from the [ASC 842 register](../lease-accounting)
commencing — the projects share one company's story.)

**3. Sign-off as a state machine.** Prepare → review → approve, with the
ordering invariant proven across all 78 task-instances. A close checklist
that cannot prove its own ordering is a spreadsheet, not a control.

## Validation (`--validate`)

1. No task starts before its dependencies finish, all six closes.
2. Sign-off ordering holds for all 78 task-instances.
3. Critical-path length equals days-to-close exactly, every month —
   recomputed independently from the graph. A "critical path" that doesn't
   equal the close duration is a diagram, not a measurement.
4. The flux control flags exactly the one seeded commentary gap
   (Prepaid expenses, Nov) and nothing else.
5. The materiality threshold is applied exactly — no sub-threshold flags,
   no missed breaches, recomputed line by line.
6. December is at least 2 days faster than July.
7. The critical path actually moved off bank reconciliation after
   automation.

## Bug the validation caught

The first critical-path walk-back picked the predecessor with the latest
*start* rather than the one whose *finish* gates the task, so parallel
branches produced a "critical path" longer than the close itself. Check 3
failed; the walk now follows the binding dependency.

## Run it

```
python3 close.py --validate
python3 close.py --html examples/close_dashboard.html --report examples/report.txt
```

Python 3.10+, standard library only. Seeded (`random.seed(1231)`).
