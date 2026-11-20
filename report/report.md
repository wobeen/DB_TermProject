# Finding the Next World-Class Player: A Snapshot-Based Derived Layer for Football Scouting in SQLite

## Abstract

Clubs spend large sums on youth prospects, yet prospect evaluation still rests heavily on individual scouts' judgement and on market value. We built a football scouting service on SQLite and Python that recommends the "next world-class" player by comparing a prospect's season record with the records of players who later became world-class at the same age. The key design is a derived layer (per-season facts, per-snapshot cohort z-scores and labels) keyed by a snapshot date, so that every recommendation is computed only from data visible at that date. On a 1.88M-appearance Transfermarkt database, the derived layer answers three scouting queries 16x to 6,237x faster than recomputing them from raw tables, with results identical to the raw path. A backtest shows that the similarity recommender is about 2.2x better than random but does not beat market value ranking, and we report this honestly. The cost is 116.5 MB of derived tables and a 14.3-second refresh per season.

## 1. Introduction

**Why it matters.** Transfer fees run into the hundreds of millions of euros, and a prospect bought at 18 may become a star or a loss. Finding such players early is among the highest-value decisions a club makes, and it is made with sparse, noisy information.

**The general problem.** Given a pool of young players and a history of past players who did or did not become world-class, rank today's prospects by their chance of following the same path. A database-backed service must answer this interactively (profile, cohort percentile, similar players) and must evaluate itself without leaking future information into the past.

**Previous approaches.** Traditional scouting relies on live observation and personal networks. *Moneyball*-style analytics and data-driven clubs such as Brentford and Brighton replaced part of this with statistical models, and commercial platforms such as Opta and Wyscout sell event-level data (passes, tackles, xG) with dashboards. Their data and models are proprietary and their event data is not available to us. The de-facto public baseline is the **market-value ranking**: sort prospects by the Transfermarkt valuation. It is cheap and strong, because it already aggregates crowd knowledge, so any new method must be compared against it.

**Proposed scheme.** We store the raw Transfermarkt data in a normalized core layer, derive per-(player, season) facts and metrics, and standardise them into age-by-position cohort z-scores per *snapshot*. A recommender then runs entirely in SQL: a weighted k-NN over z-scores finds each candidate's most similar past players at the same age, and the share of world-class neighbours is the score.

**Evaluation summary.** On the 20-player query sample, the derived layer gives median latencies of 0.25 ms (season history), 247.34 ms (cohort percentile) and 15.27 ms (k-NN), versus 1,529.88, 4,004.57 and 4,063.40 ms on raw tables without indexes: speedups of 6,236.8x, 16.2x and 266.2x, with identical results (all verification checks PASS). In the backtest (DF/MF/FW), precision@20 is 0.131 for random, 0.378 for market value, 0.294 for similarity and 0.344 for a hybrid: market value stays strongest.

**Outline.** Section 2 gives background, Section 3 the design and implementation, Section 4 the evaluation, and Section 5 concludes with limitations.

**Contributions.**

- **Analysis.** We validated what the public data supports (§2): an on-pitch interval model reproduces recorded minutes within ±5 minutes for 99.989% of appearances, and we state which scouting metrics cannot be built (no tackles, passes or xG).
- **Design and implementation.** A three-layer SQLite design (raw, derived, service) whose snapshot-keyed derived tables prevent look-ahead leakage by construction, with the k-NN recommender, set-comparison queries and a role-based CLI implemented in SQL and Python.
- **Evaluation.** A controlled comparison of raw (B1, B2) and derived (P) paths with EXPLAIN and cProfile evidence, refresh and storage cost, and a leakage-free backtest against random and market-value baselines, including the negative result.

## 2. Background and Motivation

**Scouting** is the process of identifying players whose future level exceeds their current reputation. We use the public Transfermarkt dataset (CC0, snapshot of 2026-07-06): 50,149 players, 87,744 games, 1,880,148 appearances, 1,255,088 game events and 656,301 market-value records after loading (`bench/results/env.json`). The 14 first-division leagues with consistent coverage span seasons 2012-2025; leagues added from 2024 have no appearance records and are excluded.

**What exists.** Per appearance: minutes, goals, assists, cards; per game: lineups (starter flag, available for about 99% of 2013-2025 appearances but 0% in 2012), substitution, card and goal events with minutes; and dated market values. Team goal events match the game score in 99.74% of cases.

**What does not exist.** There are no tackles, interceptions, passes, shots, saves or xG. Defenders and goalkeepers can only be described by playing time, results while on the pitch (goals against per 90, clean-sheet rate, goal difference) and league level. This limits what any recommender built on this data can know (§5). The motivation is therefore a *database* one: even with coarse data, a recommender needs expensive per-season aggregation over 1.9M rows and a time-consistent cohort definition, which is exactly what a derived layer with snapshots provides.

## 3. Design and Implementation

### 3.1 Architecture

The database has three layers. The **core layer** (9 tables, e.g. `player`, `game`, `appearance`, `game_event`, `player_valuation`) holds normalized raw data with CHECK, FK and STRICT-type constraints. The **derived layer** holds `player_season` (one row per player and season: age, minutes, on-pitch goals for/against, clean sheets, league strength), `player_season_metric` (11 metrics) and, per *snapshot*, `cohort_baseline`, `player_season_z` and `world_class_label`. The **service layer** holds users, watchlists, notes and recommendation runs with their evidence. A snapshot (`snapshot.as_of_date`) is a cut-off date: views such as `v_player_season_asof` expose only seasons ending before it, and all z-scores and labels carry `snapshot_id` in their primary key. A backtest at 2018-07-01 therefore cannot read 2019 data, which is enforced by the schema rather than by developer discipline. Refresh is explicit: `build_player_season` recomputes seasons, `build_snapshot` rebuilds one snapshot in a single transaction. The code runs in the three steps `scripts/setup_db.py` (load, derive, build two snapshots), `python -m scouting create-admin`, and `python -m scouting`; the benchmark is `python bench/run_all.py`.

![w=1.0 Figure 1. ER diagram (PK/FK marked; STRICT tables, NOT NULL/CHECK in `db/schema.sql`). Layers: core, derived, service. 1:N: club-player, player-appearance; N:M: user-player via `watchlist`.](figures/er.png)

### 3.2 Key tables and the on-pitch interval model

| Table | Key | Rows (env.json) | Role |
|---|---|---|---|
| `player_season` | (player_id, season) | 90,238 | season facts (derived) |
| `player_season_metric` | (player_id, season, metric_code) | 817,106 | 11 metrics, long format |
| `player_season_z` | (snapshot_id, player_id, season, metric_code) | 1,997,025 | cohort z, 4 snapshots |
| `cohort_baseline` | (snapshot_id, pos_group, age, metric_code) | 3,520 | mean, std, n |
| `world_class_label` | (snapshot_id, def_id, player_id) | 396,504 | label per definition |

Defender and goalkeeper quality is mostly about goals conceded *while the player was on the pitch*, which the data does not record. We reconstruct a playing interval `(in, out]` per appearance: `in` = 0 for starters or the minute of the substitution-in event; `out` = the earlier of substitution-out and sending-off minute, else infinity. A goal at minute `m` counts for the player's team if `in < m <= out`. Starters are taken from the lineup table, or, when lineups are missing (season 2012), as players with no substitution-in event. For 2018 league appearances the model reproduces `minutes_played` within ±5 minutes in **99.989%** (109,855 of 109,867) of cases (CONTRACT §1; the exploration-phase 99.996% excluded 2,855 appearances with unknown substitution time and is not used). The core of the SQL, copied from `pipeline/derive.py`:

```sql
CREATE TEMP TABLE t_pitch AS
SELECT x.game_id, x.player_id,
       COALESCE(SUM(CASE WHEN gl.club_id = x.club_id THEN 1 END), 0) AS gf,
       COALESCE(SUM(CASE WHEN gl.club_id <> x.club_id THEN 1 END), 0) AS ga
FROM t_lg0 x
JOIN t_goal gl ON gl.game_id = x.game_id
WHERE x.side_ok = 1 AND x.inn IS NOT NULL
  AND gl.club_id IN (x.home_club_id, x.away_club_id)
  AND ((gl.minute = -1 AND x.inn = 0 AND x.out_min IS NULL)
       OR (gl.minute >= 0 AND gl.minute > x.inn AND gl.minute <= COALESCE(x.out_min, 1000000)))
GROUP BY x.game_id, x.player_id
```

### 3.3 Metrics per position group

`metric_weight` (in `db/reference_data.sql`) gives each position group its own weighted metric set. GK: minutes share, start rate, goals against per 90 on pitch, clean-sheet rate, league level, UEFA minutes. DF adds on-pitch goal difference, goal contributions and cards. MF: goal contributions, assists, on-pitch goal difference. FW: goals per 90, goal contributions. All metrics are z-scored within the same snapshot, position group and age (cohort size n >= 20, std > 0), sign-flipped when lower is better, and clipped to [-4, 4]. League level (`log10` of the average market value of the league's players) lets a 19-year-old regular in a strong league outrank one in a weak league.

### 3.4 Similarity k-NN in SQL

For a candidate (player, season L), the pool is all past player-seasons of the same position group and age; distance is the weighted RMS z-difference over shared metrics, and neighbours are chosen with `ROW_NUMBER()`. Candidates sharing less than 60% of metric weight are skipped. `scouting/services/knn.py` (excerpt; Korean comment translated, line breaks condensed; only named binds, no value concatenation):

```sql
pairs AS (  -- candidate x pool (same snapshot, pos group, age; season <= pool_max; not self)
    SELECT cv.player_id AS cand_id, pz.player_id AS nb_id, pz.season AS nb_season,
           SUM(cv.weight * (cv.z - pz.z) * (cv.z - pz.z)) AS wss, SUM(cv.weight) AS sw
    FROM cv JOIN player_season_z pz
      ON pz.snapshot_id = :snap AND pz.pos_group = :pos
     AND pz.age = cv.age AND pz.metric_code = cv.metric_code
    WHERE pz.season <= :pool_max AND pz.player_id <> cv.player_id
    GROUP BY cv.player_id, pz.player_id, pz.season ),
ranked AS (
    SELECT p.cand_id, p.nb_id, p.nb_season, p.wss / p.sw AS d2,
           ROW_NUMBER() OVER (PARTITION BY p.cand_id
                              ORDER BY p.wss / p.sw, p.nb_id, p.nb_season) AS rn
    FROM pairs p JOIN ctot t ON t.player_id = p.cand_id
    WHERE p.sw * 10 >= t.tw * 6 )
```

The score is the inverse-distance-weighted share of world-class neighbours, `sum(is_wc/(d+0.1)) / sum(1/(d+0.1))`; `ix_psz_cohort` (snapshot_id, pos_group, age, metric_code, ...) is a covering index for the `pz` lookup. A `hybrid` method averages the percentile ranks of the similarity score and of the market value.

### 3.5 DB connection, transactions and ALL/SOME

All code connects only through `scouting/db.py` (autocommit connection, foreign keys on, every write wrapped in `transaction`, which nests as SAVEPOINT; excerpt of `connect` and `transaction`, docstrings and the SAVEPOINT branch elided):

```python
conn = sqlite3.connect(db_path(path), isolation_level=None)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("PRAGMA busy_timeout = 5000")
...
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
```

A recommendation run, its items and its evidence are written inside one `with transaction(conn):` (`recommend.py`), and `build_snapshot` also deletes and rebuilds in one transaction, so a failure leaves no half-written run or snapshot. User values are always `?` or `:name` binds.

**Set comparison (ALL/SOME).** The "breakout prospects" feature lists candidates whose metric exceeds *every* (or *some*) world-class player of the same age. SQLite has no `ALL`/`SOME`, so `x > ALL(S)` is rewritten as `NOT EXISTS (... s >= x)` and `x > SOME(S)` as `EXISTS (... s < x)`; tests compare them with `x > MAX(S)` and `x > MIN(S)`. From the comment block in `scouting/services/recommend.py` (translated from Korean, whitespace condensed):

```python
#   mode="all":  cv.value >  ALL (SELECT s.value FROM s WHERE s.age = cv.age)
#                NOT EXISTS (SELECT 1 FROM s WHERE s.age = cv.age AND s.value >= cv.value)
#   mode="some": cv.value >  SOME (SELECT s.value FROM s WHERE s.age = cv.age)
#                EXISTS     (SELECT 1 FROM s WHERE s.age = cv.age AND s.value <  cv.value)
```

If `S` is empty, `x > ALL(S)` is vacuously true for every candidate, which would flag everyone. The query therefore adds `WHERE EXISTS (SELECT 1 FROM s WHERE s.age = cv.age)`, so ages with no world-class reference return nothing, and the CLI explains why. (`x > SOME(S)` is false on an empty set, so only ALL needs the guard.)

### 3.6 CLI functions and execution results

`python -m scouting` has a scout menu (search, profile, similar players, recommendation, history, watchlist, notes, breakout) and an admin menu (data status, snapshot rebuild, definition management, backtest, roles), with Korean console text. Menu 3 calls `players.similar_players`, which runs the k-NN above (output of `report/console/menu3_similar.txt`, snapshot `current`, definition 1):

```
시즌 2025 기준 유사 선수 Top-5
순위 |      ID | 이름                  | 시즌 | 나이 | 구단              | 거리  | 월클
   1 |  467720 | Youssoufa Moukoko     | 2022 |   17 | Borussia Dortmund | 1.078 | -
   2 |  532826 | Mason Greenwood       | 2019 |   17 | Manchester United | 1.098 | O
   3 |  342229 | Kylian Mbappé         | 2016 |   17 | AS Monaco         | 1.174 | O
```

Menu 8 with `minutes_share`, FW, snapshot `current` returned no row for ALL (no candidate exceeds every world-class value of his age; e.g. 89 comparison values at age 20), and 84 for SOME (top row: `Jorg Schreuders, age 20, 0.925, 89 comparison players, max 0.934, min 0.003`). Menu 4 (DF, `similarity`, default parameters, 107 candidates, 0.7 s) prints the ranking with the world-class neighbour count:

```
FW / minutes_share / SOME 비교: 84명
순위 |      ID | 이름            | 나이 |    값 | 비교 월클 수 | 월클 최댓값 | 월클 최솟값
   1 |  671735 | Jorg Schreuders |   20 | 0.925 |           89 |       0.934 |       0.003
   2 |  748804 | Mika Godts      |   20 | 0.878 |           89 |       0.934 |       0.003
```

```
순위 |      ID | 이름         | 구단          |  점수 | 월클이웃 | 시장가치(as_of)
   1 |  924117 | Finn Jeltsch | VfB Stuttgart | 0.388 |        9 | €35.0M
   2 | 1121298 | Juma Bah     | OGC Nice      | 0.322 |        9 | €10.0M
```

### 3.7 Disadvantages, stability and robustness

*Overhead.* The derived layer duplicates information. Its six tables take 116.5 MB (VACUUM difference) and the 15 `ix_` indexes add 301.2 MB (581.3 to 882.5 MB, +52%). `player_season_z` deliberately denormalizes `age` and `pos_group` to serve the k-NN index, so consistency depends on the build code writing both in one transaction. Data changes require refresh: one season costs 14.3 s (full rebuild of 2012-2025: 180.5 s, so 8%), and a snapshot rebuild costs 10.1 to 58.0 s (`bench/results/refresh.csv`). *Why this is acceptable.* The source dataset is a static CC0 release and a new season arrives at most once a year, so a refresh of about a minute is amortised over every query: one raw-path k-NN costs about 4 s, and a derived-path one 15 ms. Storage of 117 MB is 13% of the 882.5 MB database. *Robustness.* Constraints (STRICT types, CHECK, FK, UNIQUE) reject bad rows in the DB; scout-owned rows are updated only with `WHERE ... AND user_id = ?`; the CLI catches `IntegrityError` and malformed input without exiting. Known weaknesses from our code review (`docs/reviews/review_pipeline_app.md`): the service API trusts callers for some read paths, and test coverage of the hybrid formula is thin.

## 4. Evaluation

**Setup.** Windows 11 (10.0.26300), Intel64 Family 6 Model 189, 8 logical CPUs, Python 3.14.0, SQLite 3.50.4 (`env.json`). Sample: 20 players (seed 42, 5 per position group), season 2025, aged 16-21, at least 900 league minutes. Three configurations: **B1** = recompute from raw tables with all `ix_` indexes dropped; **B2** = raw path with indexes; **P** = derived tables plus indexes. Queries: Q1 season history, Q2 cohort percentile, Q3 k-NN (k=10). The raw path (`bench/raw_queries.py`) evaluates the §3.2 formulas in one `WITH` query, and its results equal P (metric error <= 1e-9, same neighbours and labels): all eight verification checks PASS. *Deviation from the planned protocol:* raw-path Q2/Q3 used 1 warm-up and 5 runs per player instead of 3 + 30 (Q1/B1: 1 + 10) because one run takes seconds; P and Q1/B2 used 3 + 30. Q3/B1 with definition 2 was verified on 3 players only (about 50 s per query).

![w=1.0 Figure 2. (a) Median query latency, log scale (`query_summary.csv`). (b) Backtest precision@20, mean over DF/MF/FW cells (`backtest.csv`).](figures/perf.png)

**Latency.** Median (p95) in ms, with speedup over B1:

| Query | B1 | B2 | P |
|---|---|---|---|
| Q1 season history | 1,529.88 (1,632.16) | 15.26 (22.72), 100.3x | 0.25 (0.40), 6,236.8x |
| Q2 cohort percentile | 4,004.57 (4,458.73) | 3,056.09 (3,581.21), 1.3x | 247.34 (302.52), 16.2x |
| Q3 k-NN | 4,063.40 (4,408.22) | 3,135.54 (3,630.22), 1.3x | 15.27 (21.05), 266.2x |

**Why P is faster (EXPLAIN, cProfile).** In B1, `EXPLAIN QUERY PLAN` shows full scans (`SCAN a`, `SCAN seasons`, `SCAN pairs`) and temporary `AUTOMATIC INDEX` builds, 16, 17 and 25 for Q1, Q2 and Q3. Indexes in B2 turn these into `SEARCH ... USING INDEX ix_appearance_player_date`, but the interval and cohort aggregation is still recomputed per query (automatic indexes: 11, 12, 20), which is why Q2 and Q3 gain only 1.3x. In P, no raw table is touched and Q3's plan reads `SEARCH z USING PRIMARY KEY (snapshot_id=? AND player_id=? AND season=? AND metric_code=?)` and `SEARCH pz USING COVERING INDEX ix_psz_cohort (snapshot_id=? AND pos_group=? AND age=? AND metric_code=?)` (one automatic index). cProfile of one `similarity` recommendation (84 FW candidates, 0.975 s total) attributes 0.941 s to 6 calls of `sqlite3.Connection.execute`; Python code is small (`knn.py:knn` 0.019 s own time, `executemany` 0.006 s, `math.sqrt` 2,100 calls). A raw-path Q3 (B1) spends 3.075 s of 3.077 s in 2 `execute` calls. The bottleneck is the number of rows SQL touches, and the derived layer reduces it. Q2 keeps 247 ms because its cohort percentile counts over a whole age-position cohort for each metric.

Excerpts (first lines of each plan) of `bench/results/explain/Q3_B1.txt` (raw, no index) and `Q3_P.txt` (derived):

```
Q3_B1:  SCAN seasons / SEARCH p USING AUTOMATIC PARTIAL COVERING INDEX (pos_group=?)
        SCAN pairs / SCAN a / SEARCH g USING INTEGER PRIMARY KEY (rowid=?)
Q3_P:   SEARCH player_season USING PRIMARY KEY (player_id=? AND season=?)
        SEARCH z USING PRIMARY KEY (snapshot_id=? AND player_id=? AND season=?)
        SEARCH pz USING COVERING INDEX ix_psz_cohort (snapshot_id=? AND pos_group=? AND age=? AND metric_code=?)
```

**Refresh cost.** `build_player_season` for 2025: 14.3 s (three runs 16.3, 14.3, 13.5 s); for 2012-2025: 180.5 s. `build_snapshot(current)`: 58.0 s as measured alone (21.8 s after a full rebuild), `bt2018`: 10.1 s.

**Backtest versus baselines (R-20).** For snapshots 2018-07-01, 2019-07-01 and 2020-07-01 we recommend the top 50 players aged at most 21 with at least 900 minutes per position group and world-class definition, using only data visible at the snapshot, and score against players who are world-class in the `current` snapshot (2026-07-07). Definition 1 is peak market value of at least €50M (GK €30M); definition 2 is three big-5 league regular seasons plus 900 CL minutes. Random is the mean of 10 seeds. Goalkeepers have 5 to 10 candidates and 1 to 2 positives per cell, so precision@20 equals positives/20 for every method and carries no information; we report DF/MF/FW (18 cells):

| Method | P@20 | P@50 | R@20 | R@50 | W/T/L vs market value |
|---|---|---|---|---|---|
| random | 0.131 | 0.126 | 0.235 | 0.567 | - |
| market_value | 0.378 | 0.211 | 0.696 | 0.949 | - |
| similarity | 0.294 | 0.186 | 0.546 | 0.847 | 3 / 3 / 12 |
| hybrid | 0.344 | 0.206 | 0.638 | 0.930 | 3 / 5 / 10 |

Including GK the means are 0.117, 0.302, 0.240 and 0.277 (24 cells; similarity vs market value 3/9/12). **Market value is the strongest baseline.** The similarity method is about 2.2x better than random (0.294/0.131) but loses to market value, and combining both closes part of the gap without overtaking it. By definition (DF/MF/FW), market value beats similarity on both: 0.311 vs 0.256 for definition 1 and 0.444 vs 0.333 for the less circular definition 2 (computed from `backtest.csv`). Market value shares its variable with definition 1, which favours it; the loss on definition 2 shows that this is not the whole explanation. Likely causes are the missing event data (no passes, tackles, xG), which make z-profiles of different players hard to distinguish, and valuations that already reflect scouts' knowledge. DF/MF/FW cells have only 5 to 17 positives each, no confidence intervals were computed, and the three snapshots are not independent.

## 5. Conclusion

**Findings.** (1) A snapshot-keyed derived layer is an effective database design for scouting analytics: 16.2x to 6,236.8x faster than raw recomputation with identical results, at 117 MB and about 14 s per season refresh, and it makes look-ahead leakage structurally impossible. (2) Indexes alone are not enough: B2 gives 100.3x for the simple Q1 but only 1.3x for Q2 and Q3. (3) The recommender is a real signal (about 2.2x random) but not a better one than market value; we report this negative result unadjusted.

**Limitations.** The data has no event-level statistics, so GK and defender profiles rest on on-pitch goals and playing time; world-class definitions and thresholds are arbitrary; the backtest has few positives, right-censored outcomes for recent snapshots and no significance tests; the hybrid and similarity parameters (k=25, pool lag 3) were not tuned; the raw-path timings used fewer repetitions.

**What could be done better.** Add event data (e.g. StatsBomb open data or xG) to give the z-profiles discriminating power; learn metric weights instead of fixing them by hand, still inside SQL; update snapshots incrementally instead of rebuilding them; add confidence intervals over more snapshots; and tighten service-layer permission checks, as found in our review.
