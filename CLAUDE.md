# CLAUDE.md — finance repo conventions

Read this first. It lets a fresh session build a new project without re-deriving
the house style, and it is why sessions here can be short.

## What this repo is

A portfolio of self-contained finance tools. Each top-level folder is one
project: a data generator, an analysis script, a live HTML dashboard, and a
README. All data is **synthetic and seeded**. Published to GitHub Pages at
lumimama.github.io/finance; the landing page is `index.html`.

Public identity is **Lumimama** — never write a real name, real company, or
real financial data into this repo.

## Standard project layout

```
<project>/
  make_sample_data.py      # seeded generator (or generation lives inside the analysis script)
  <analysis>.py            # the model/engine
  README.md                # the write-up
  data/                    # generated CSVs (committed)
  examples/                # generated dashboard + console output (committed)
```

## The non-negotiables (every project follows these)

- **Python 3.10+, standard library only.** The one exception is
  `variance-narrator`, which uses `pandas` + the `anthropic` SDK. No plotting
  libraries, no template engines, no JS frameworks — anywhere.
- **Deterministic.** Every generator is seeded (`random.seed(...)`). Re-running
  produces byte-identical output.
- **A `--validate` mode that must PASS before the dashboard publishes.** It
  recomputes the core identities from raw components (walks tie, balances
  balance, roll-forwards reconcile) or scores the analysis against seeded
  ground truth (`seeded_*.json`). A green validate is the quality bar.
- **A `--html <path>` mode** that writes ONE self-contained file: inline CSS +
  inline SVG charts, no CDN, no network at load, theme-aware (light/dark via
  `prefers-color-scheme`), body never scrolls horizontally (wide tables/charts
  scroll inside their own `overflow-x:auto` container).
- **Nothing hardcoded in the HTML** that should be computed — every rendered
  number comes from the data at generation time.

## Dashboard styling

Copy the `:root` CSS variable block and the `@media (prefers-color-scheme: dark)`
override from any existing dashboard (they are identical across projects):
`--fg --mut --bg --line --grid --neg --pos --card --bd`. Cards, KPI tiles,
tables, and SVG charts all reference those vars. Match an existing project's
dashboard rather than inventing new styling.

## Design → build order (keeps sessions cheap)

1. Decide the seeded findings the data should contain (the "story"), and the
   validation checks that prove the analysis surfaces them — **before** writing
   the generator.
2. Write the generator; run it.
3. Write the analysis with `--validate`; iterate until it PASSES.
4. Only then write the HTML and the README.

Document bugs the validation caught in the code comments — that trail is a
feature of the READMEs, not noise to clean up.

## Before publishing — freshness

`--validate` checks the ANALYSIS. It cannot see the PUBLISHED HTML, so a
dashboard can drift from its data (an external audit found a hardcoded "1,450
customers" header against a 1,448-row dataset). Two rules:

- **Never hardcode a figure in an HTML template.** Every rendered number comes
  from the data at generation time.
- **Run `python3 check_freshness.py` before every push.** It fails if any
  `examples/*.html` is older than the script or data that produce it.
- Note: several scripts rewrite their `data/*.csv` on every run, so a
  `--validate` sweep across all projects will legitimately mark dashboards
  stale. Regenerate the HTML after any sweep — that is the guard working, not
  a false alarm.

## Publishing

```
git add -A && git commit -m "..." && git push origin main
```

GitHub Pages redeploys automatically (~1 min). Verify with curl, not
screenshots:

```
curl -s -o /dev/null -w "%{http_code}" "https://lumimama.github.io/finance/<project>/examples/<dashboard>.html"
```

When adding a project: also add a card to `index.html` (grouped grid — Payments
/ Revenue analytics / Planning & cash / Reporting, metrics & controls) and a row
to the table in `README.md`.

## Token discipline

- Pipe long command output through `tail`/`head`.
- Prefer `Edit` (diff) over `Write` (whole file) when changing an existing file.
- Verify deploys with `curl | grep`, not screenshots.
- Read large files (xlsx, PDF, big CSV) by range/sheet, not whole.
