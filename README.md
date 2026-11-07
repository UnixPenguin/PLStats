# PLStats

### 👉 [**Open the calculator: unixpenguin.github.io/PLStats**](https://unixpenguin.github.io/PLStats/)

**How strong are you, really?** Enter your squat, bench, deadlift and bodyweight and see how you stack up against
ten years of powerlifting meets from [OpenPowerlifting](https://www.openpowerlifting.org), with lifters from around
the world. You're compared with US drug-tested raw lifters unless you pick another group, such as everyone worldwide.
It's free, there's no sign-up, and nothing you type leaves your browser.

## About this project

PLStats started as my final project for an advanced statistics course. This version was edited and extended with help from AI (Claude): it cleaned up the analysis, turned it into the interactive calculator, and set up the weekly data refresh. I reviewed the results, but mistakes are possible. A few things to keep in mind when using it:

- The comparisons are against people who **compete** in powerlifting, not the general public, so a middling percentile here can still be very strong by everyday standards.
- N-Score is an experimental formula from this project. It isn’t recognized by any federation.
- Results come straight from OpenPowerlifting. If a lifter’s meet record is wrong, report it to OpenPowerlifting so it gets fixed at the source.
- This is a statistics project, not coaching or medical advice.

If you find a bug, a wrong number or a confusing explanation, please open an issue. For questions, ideas or general feedback, use Discussions. Suggestions and pull requests are welcome.

## What you get

- **Pick who you're compared with**: US or worldwide, drug-tested only or all federations, raw or raw + knee wraps,
  and Open/Junior/College divisions or all ages.
- **Your scores**: Dots, Wilks, IPF GL and **N-Score** (a formula made for this project), each with a percentile.
  You're compared with each lifter's best meet, so someone with twenty meets still counts once.
- **Where you rank**: your percentile for squat, bench, deadlift and total, in your weight class or across all weights.
- **Compared with lifters like you**: the total that's typical for your bodyweight, sex and age, and how far above
  or below it you are.
- **Your strength profile**: whether you're squat-, bench- or deadlift-heavy, and where you sit on a map of everyone
  in your group. You can add up to five other lifters to the map, out of about 400,000 from around the world.
- **The stats**: the methods and charts behind every number, tucked away at the bottom of the page.

The data refreshes automatically every week from the latest OpenPowerlifting release.

<!-- DATA-START (this block is rewritten by run_pipeline.py; do not edit by hand) -->
## Current data

**OpenPowerlifting snapshot: 2026-10-31** · meets from 2016-10-29 to 2026-10-25 · default group (US, drug-tested, raw): 92,475 lifters (59,819 men, 32,657 women) with 218,653 results · last refreshed 2026-11-07

| Key result | Men | Women |
|---|---:|---:|
| N-Score version 2 (2026-11-07): Total = a · BW^b | 54.42 · BW^0.510 | 59.87 · BW^0.380 |
| N-Score correlation with bodyweight | -0.032 | -0.013 |
| Dots correlation with bodyweight | +0.001 | -0.145 |
| Spread of the squat/deadlift ratio (variance of its log) | 0.0145 | 0.0191 |
| Spread of the squat/bench ratio (variance of its log) | 0.0193 | 0.0259 |
| Spread of the deadlift/bench ratio (variance of its log) | 0.0221 | 0.0242 |

The smaller the spread, the more alike lifters are in that ratio.

Mean of lifters' best scores, men ÷ women: N-Score 0.989, Dots 1.138. Regression: R² = 0.715, typical error 83 kg, peak age 29.5 (from comparing lifters of different ages, not following anyone over time). Unique ΔR²: sex 0.311, bodyweight 0.073, age 0.012, year 0.003.

Charts in [`figures/`](figures/) are from snapshot 2026-10-31.
<!-- DATA-END -->

## Who's in the comparison

Every group uses **full-meet** results (squat, bench and deadlift) from the last ten years, and each lifter counts
once, at their best. Disqualifications and bomb-outs (missing all three attempts on a lift) are left out, and so are
results where one lift is under 15% of the total (usually a token lift just to get a total). You can change four things:

| Option | Default | Alternative |
|---|---|---|
| Region | US lifters | Worldwide |
| Drug testing | Drug-tested federations only | Tested and untested |
| Equipment | **Raw** (belt and knee sleeves) | Raw + knee wraps |
| Divisions | Open, Junior (18+) and Collegiate | All ages (including youth, sub-juniors and masters) |

Equipped lifting (squat suits and bench shirts) is never included, because those numbers aren't comparable.

Your percentiles, expected total and profile map use the group you pick. The research behind the site (the N-Score
fit, the regression, the PCA and the numbers under "Current data") uses the default US group, so your N-Score doesn't
change when you switch groups.

## The scoring formulas

All four formulas adjust your total for bodyweight, so lifters of different sizes can be compared.

| Formula | What it is |
|---|---|
| **Wilks** (1994) | The classic formula, built from elite results in the 1990s, when far fewer women competed. |
| **Dots** (2019) | Developed by Tim Konertz as an update of the same idea, using modern data. Widely used by powerlifting federations worldwide, though some have started moving away from it. |
| **IPF GL** (2020) | The IPF's "Goodlift" points, the official scoring standard of the IPF. Around 100 is elite international level. |
| **N-Score** | A new, experimental formula made for this project. With the other three, heavier women score lower on average than lighter women; with N-Score, women score about the same on average at any bodyweight. (For men, all four are already fairly even.) The catch: among the top 1%, women score a bit higher than men. |

### About N-Score

- **It's updated every week** with the latest data, so the same total can score slightly differently from one week
  to the next. Your score shows which version (number and date) it came from.
- **Old versions are saved** in [`docs/data/nscore_history.json`](docs/data/nscore_history.json), so any past score can
  be recalculated.
- **Men and women average about the same on purpose.** N-Score uses a separate curve for each sex, so this doesn't
  prove the formula is fair between men and women.

## How it works

A Python pipeline cleans the OpenPowerlifting data, builds every comparison group (US and worldwide), and runs the
analysis on the default US group:

- a principal component analysis (PCA) of how each lifter's total splits between the three lifts;
- the N-Score fit, tested on lifters it wasn't fitted to;
- a regression that predicts a total from bodyweight, sex, age and meet year. It explains about 70% of the differences
  between lifters; the rest is things the data can't see, like training and genetics. Its "peak age" compares lifters of
  different ages, not the same people over time, so it isn't a forecast of when you'll peak.

The results are saved as data files that the website reads. There's no server.

Want to run it yourself?

```bash
pip install -r requirements.txt
python scripts/download_data.py   # latest OpenPowerlifting CSV, ~170 MB download
python run_pipeline.py            # writes docs/data/, figures/ and results/summary.md
python tests/test_pipeline.py     # optional: checks on small made-up data
python -m http.server -d docs 8000
```

Each refresh is checked before it goes live, so if something goes wrong the site stays as it was. Detailed numbers
are in [`results/summary.md`](results/summary.md), and static charts are in [`figures/`](figures/).

## Credits

This project uses data from the OpenPowerlifting project, https://www.openpowerlifting.org.
You can download a copy of the data at https://gitlab.com/openpowerlifting/opl-data.
PLStats is not affiliated with OpenPowerlifting. Code is MIT licensed.
