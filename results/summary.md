# PLStats results

Data: 2016-10-29 to 2026-10-25 (snapshot 2026-10-31), 218,653 results from 92,475 lifters. Percentiles, histograms, the profile map and the formula evaluation count each lifter once (their best result for that metric).

## Cleaning

| Step | Rows left |
|---|---:|
| Full OpenPowerlifting dataset | 4,059,940 |
| US lifters only | 2,130,779 |
| Drug-tested federations | 1,634,235 |
| Raw (unequipped) | 560,610 |
| Full meet (squat + bench + deadlift) | 432,781 |
| Last 10 years | 376,868 |
| Open / Junior / Collegiate divisions | 228,522 |
| Drop DQ, bomb-outs, no-shows, guests | 219,617 |
| Every lift >= 15% of total | 218,695 |
| Bodyweight recorded, sex M/F | 218,653 |

## PCA (one row per lifter: best meet by Dots)

Raw kg (z-scored) variance explained: PC1 94.3%, PC2 3.4%, PC3 2.3%

### Lift log-ratios (clr), M (n = 59,819 lifters)
Variance explained: PC1 61.93%, PC2 38.07%, PC3 0.00%
Mean shares: Squat 35.6%, Bench 23.4%, Deadlift 41.0%

| Loading | PC1 | PC2 |
|---|---:|---:|
| Squat | +0.274 | +0.769 |
| Bench | -0.803 | -0.147 |
| Deadlift | +0.529 | -0.622 |

Variance of log-ratios: squat/deadlift 0.0145, squat/bench 0.0193, deadlift/bench 0.0221
Correlation of bodyweight with shares: Squat +0.212, Bench +0.157, Deadlift -0.323

### Lift log-ratios (clr), F (n = 32,657 lifters)
Variance explained: PC1 58.75%, PC2 41.25%, PC3 0.00%
Mean shares: Squat 36.3%, Bench 20.2%, Deadlift 43.5%

| Loading | PC1 | PC2 |
|---|---:|---:|
| Squat | +0.488 | +0.655 |
| Bench | -0.811 | +0.095 |
| Deadlift | +0.323 | -0.750 |

Variance of log-ratios: squat/deadlift 0.0191, squat/bench 0.0259, deadlift/bench 0.0242
Correlation of bodyweight with shares: Squat +0.158, Bench +0.050, Deadlift -0.191

## Scoring formulas

N-Score fit #2 of 2 (fit 2026-11-07, snapshot 2026-10-31); all fits: docs/data/nscore_history.json.
Method: v2: ln(Total) = ln(a) + b*ln(BW) by least squares, each lifter's results weighted to a total of 1; scale = 500 / 99th percentile of lifters' best Total/(a*BW^b), both sexes pooled

| Sex | a | b | R² (log) | test R² power | test R² poly5 | results | lifters |
|---|---:|---:|---:|---:|---:|---:|---:|
| M | 54.42 | 0.510 | 0.254 | 0.249 | 0.285 | 141,533 | 59,819 |
| F | 59.87 | 0.380 | 0.153 | 0.140 | 0.167 | 77,120 | 32,657 |

N-Score scale factor: 334.00

The men/women mean ratio of about 1 for N-Score follows from fitting each sex separately; it is not independent evidence that N-Score is fair across sexes.

| Formula | r(BW) men | r(BW) women | M/F mean | M/F p99 |
|---|---:|---:|---:|---:|
| Wilks | +0.023 | -0.195 | 1.141 | 1.044 |
| Dots | +0.001 | -0.145 | 1.138 | 1.049 |
| IPF GL | +0.003 | -0.110 | 1.129 | 1.040 |
| N-Score | -0.032 | -0.013 | 0.989 | 0.915 |

## Regression

n = 215,927 results from 90,633 lifters with a recorded age (2,726 results without an age left out); R² (log) = 0.715; R² (kg) = 0.702; RMSE = 82.8 kg; peak age = 29.5 (cross-sectional)

SE: cluster-robust (CR1) by lifter; naive i.i.d. SE shown for comparison.

| Term | Coef | SE (clustered) | SE (i.i.d.) | % change in total |
|---|---:|---:|---:|---:|
| zBW | +0.0861 | 0.0016 | 0.0007 | +9.0% |
| Male | +0.4617 | 0.0021 | 0.0010 | +58.7% |
| zBW x Male | +0.0307 | 0.0019 | 0.0009 | +3.1% |
| zAge | +0.0146 | 0.0011 | 0.0005 | +1.5% |
| zAge^2 | -0.0169 | 0.0004 | 0.0002 | -1.7% |
| zYear | +0.0195 | 0.0006 | 0.0004 | +2.0% |

Unique ΔR²: Bodyweight 0.073, Sex 0.311, Age 0.012, Year 0.003
