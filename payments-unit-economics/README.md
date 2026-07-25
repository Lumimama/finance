# Payments Unit Economics

Per-transaction contribution by rail, region, and merchant segment, from 120,000 transactions over a quarter — the analysis behind *"which volume do we actually want more of?"*

**No dependencies.** Python 3.10+, runs in ~2 seconds.

```bash
python make_sample_data.py    # regenerate the dataset (seeded)
python unit_economics.py      # console report
python unit_economics.py --html examples/unit_econ_dashboard.html
```

## Why per-transaction and not per-P&L-line

A payments P&L aggregates rails with wildly different economics, so blended margin can look healthy while the mix quietly rots. Decisions — pricing, incentives, which corridors to push — happen at the unit level. The model works there and only then rolls up.

The contribution stack per transaction:

```
  revenue           take-rate on volume + fixed fee
  − rewards         funding the issuer-side value prop (credit rails)
  − fraud loss      realized, not provisioned
  − chargebacks     realized loss + $12 per-event ops cost
  − processing      per-transaction network/compute cost
  − incentives      merchant/consumer promos
  = contribution    per transaction, and in bps of volume
```

## What the numbers say

```
BY RAIL
                         txns       volume       take    contrib  contrib/txn   margin     fraud
cross_border           10,786   $1,407,074  302.5 bps  197.0 bps      $2.5706   65.1%  16.3 bps
ecom_credit            25,244   $2,046,704  153.5 bps   50.3 bps      $0.4079   32.8%   6.0 bps
domestic_credit        34,937   $2,135,376  131.3 bps   38.4 bps      $0.2349   29.3%   4.9 bps
domestic_debit         39,494   $1,396,119   64.7 bps   49.4 bps      $0.1748   76.4%   2.4 bps
tap_to_pay              9,539     $220,142  101.0 bps   49.6 bps      $0.1145   49.1%   0.0 bps
```

Three findings that would survive contact with a pricing committee:

**Cross-border is the crown jewel, fraud and all.** 302 bps of take, 197 bps of contribution, 65% margin — even carrying 16 bps of fraud, seven times the domestic-debit rate. A transaction of equal size earns ~15× more crossing a border than staying home. This is why every payments company's investor deck leads with cross-border volume.

**Take rate and margin are different questions.** Domestic credit has twice the take of debit (131 vs 65 bps) and less than half the margin (29% vs 76%), because rewards funding consumes most of the credit take. Ranking rails by take rate — which is what a revenue-only view does — gets the priority order wrong.

**The waterfall names the real cost center.** Of $113K net revenue, rewards consume $41K — more than fraud, chargebacks, processing, and incentives combined. Fraud gets the headlines; rewards funding is the structural cost.

## Mix-shift sensitivity

Each rail's unit economics held fixed; pure mix effect — the question pricing committees actually ask:

```
scenario                                  blended contrib   Δ vs base  Δ contribution $
base                                             75.3 bps
Cross-border volume 2x                           95.2 bps    +19.9 bps          $27,726
Tap-to-pay volume 2x                             74.5 bps     -0.8 bps           $1,092
E-com credit +50%                                72.2 bps     -3.1 bps           $5,148
Debit shifts to credit (-25% / +25%)             73.8 bps     -1.4 bps             $326
```

The last row is the subtle one: a debit→credit mix shift raises *revenue* and barely moves *contribution* — the extra take is consumed by rewards. A revenue-weighted view would call that shift a win; a contribution-weighted view calls it a wash.

`--html` renders all of it — KPIs, waterfall, three rollup tables, and the sensitivity — as one self-contained page. See [`examples/unit_econ_dashboard.html`](examples/unit_econ_dashboard.html).

## Data

Fully synthetic, seeded, reproducible: 120,000 transactions across five rails, four regions, six merchant segments, with log-normal ticket distributions and per-rail fee, rewards, fraud, and chargeback parameters. The *numbers* are invented; the *structure* — which rails earn more, which costs scale with volume versus count, where the cross-border premium comes from — is faithful to how payment platforms actually earn.

## Notes

Built with Claude as a pair.
