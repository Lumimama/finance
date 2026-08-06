# Lease Accounting — ASC 842

**Live dashboard:** [leases_dashboard.html](https://lumimama.github.io/finance/lease-accounting/examples/leases_dashboard.html)

A 26-lease register (offices, vehicles, lab equipment, one GPU capacity
agreement) with full monthly amortization schedules, classification tests,
and the disclosure maturity table — built so that every schedule must land
at **exactly zero** and the footnote must tie to the balance sheet, or the
dashboard does not publish.

## The three findings the data was designed to contain

**1. The embedded lease.** A "GPU capacity services agreement" — 48 months,
$240K/month, dedicated racks — never uses the word "lease." ASC 842's tests
disagree: an identified asset (specific, physically distinct hardware, no
supplier substitution right) that the customer controls (decides what runs
on it, receives substantially all its output). At $10.1M it moves the
balance sheet more than every office combined, and the specialized-asset
criterion makes it a finance lease. This is the live 842 question for AI
companies: compute contracts signed as "services" that contain dedicated
hardware. The register exists to catch them at signing, not at audit.

**2. The judgment at the line.** The London office prices out at
PV of payments / fair value = **88.9%** — deliberately just under the 90%
"substantially all" practice threshold. Classification: operating, with the
ratio printed on the register instead of buried in a workpaper. ASC 842
removed the bright lines on purpose; what replaces them is documented
judgment.

**3. The exemption as a control.** Two sub-12-month leases take the
short-term exemption — straight-line expense, no ROU, no liability — and
validation *asserts they stay off the balance sheet*. An exemption applied
is also a control to test.

## Identities enforced by `--validate`

1. Opening liability = PV of payments at the incremental borrowing rate, to
   the cent, for all 26 capitalized leases.
2. Liability roll-forward (beginning + interest − payment = ending) lands at
   **exactly zero** in the final month of every lease.
3. ROU amortizes to exactly zero — straight-line for finance leases; for
   operating leases amortization is the plug that keeps single lease cost
   level.
4. Operating leases: lifetime cost = lifetime payments, and the monthly cost
   is level to the cent (this is what catches escalator mistakes).
5. The disclosure maturity table ties: undiscounted payments ($21.98M) −
   imputed interest ($2.31M) = carrying amount ($19.67M), recomputed from
   raw schedules.
6. The embedded lease is present, classified finance, and on the balance
   sheet at the reporting date.
7. Exactly one lease sits in the 85–90% PV/FV band, classified operating.
8. Short-term leases stay off-balance-sheet; weighted-average IBR lands in a
   sane band (6.18%).

## Bugs the validation caught

- **Escalating office leases were first straight-lined from initial monthly
  rent**, not total payments over the term. Every escalating lease failed
  the lifetime-cost identity by exactly the sum of its escalations.
- **The judgment-case lease was first given a hand-picked fair value** and
  its PV/FV landed above 100%, silently classifying it finance and leaving
  the 85–90% band empty. Check 7 refused to pass; the fair value is now
  derived from the computed PV so the ratio lands where the design says.

## Simplifications (stated, not hidden)

- No initial direct costs, incentives, or prepaid rent (ROU = opening
  liability at commencement).
- No modifications or remeasurements during the year — the register is a
  statics exercise; a modification engine would be the natural extension.
- IBR by commencement year + asset-class spread; practice thresholds (75%
  of economic life, 90% of fair value) stand in for ASC 842's removed
  bright lines, as they do in most policy memos.

## Run it

```
python3 leases.py --validate
python3 leases.py --html examples/leases_dashboard.html --report examples/report.txt
```

Python 3.10+, standard library only. Seeded (`random.seed(842)`) —
re-running reproduces every figure exactly.
