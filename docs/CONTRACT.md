# 구현 계약서 (CONTRACT)

축구 유망주 스카우팅 DB: "다음 월드클래스" 추천 서비스. 기획 배경: [PLANS.md](./PLANS.md) 기획안 E, 요구사항: [REQUIREMENTS.md](./REQUIREMENTS.md).

이 문서와 `db/*.sql`, `scouting/db.py`가 에이전트 사이의 **고정 계약**이다. 변경은 coordinator만 하며, 변경이 필요하면 작업을 멈추고 coordinator에게 질문한다.

---

## 0. 확정 결정

| 항목 | 결정 |
|---|---|
| 종목 / 데이터 | 축구. Transfermarkt 데이터셋(`dcaribou/transfermarkt-datasets`, CC0), 2026-07-06 스냅샷 |
| DBMS | SQLite ≥ 3.37 (STRICT 테이블). 단일 파일 `data/scouting.sqlite` |
| 언어 | Python ≥ 3.11. 런타임은 표준 라이브러리만 쓴다. 개발용은 `pytest`, 벤치 그래프는 `matplotlib` |
| 인터페이스 | CLI (`python -m scouting`, 한국어 메뉴, 스카우팅 전체 기능) + GUI (`python -m scouting.gui`, Tkinter + matplotlib, **읽기 전용 선수 커리어 탐색기**: 검색·이적 이력·시즌별 기록·시장가치. 월클/추천 기능 없음). 두 화면 모두 `scouting/services`만 호출한다 |
| 추천 로직 | **SQL로 구현한다.** ML 라이브러리(numpy, pandas, sklearn 등)는 금지. Python은 오케스트레이션과 seed 기반 셔플만 맡는다 |
| 보고서 | 영어 본문, 6페이지. CLI 화면 출력은 한국어 그대로 |
| 포지션 범위 | GK, DF, MF, FW 전체. 포지션군별 지표 가중치는 `metric_weight` 테이블로 정의 |

## 1. 데이터 검증 결과 (coordinator 실측)

원천 12개 테이블. 출전 기록은 2012~2025 시즌이며 행 수는 다음과 같다.

| 테이블 | 행 수 |
|---|---|
| appearances | 1,894,350 |
| game_lineups | 3,179,016 |
| game_events | 1,274,469 |
| player_valuations | 656,301 |
| players | 50,149 |

| 확인 항목 | 결과 |
|---|---|
| 출전 기록 커버리지 | 1부 리그 14개(GB1, ES1, IT1, L1, FR1, PO1, NL1, BE1, TR1, RU1, UKR1, SC1, GR1, DK1)가 2012~2025 시즌 100% 가깝게 수집됨. 2024년부터 추가된 리그(MLS, K리그 등)는 출전 기록이 0건이라 제외한다 |
| 라인업(선발 여부, 경기별 포지션) | 2013~2025 시즌은 약 99%. **2012 시즌은 0%** → 선발 여부는 대체 규칙(§3.2)으로 판정 |
| 득점 이벤트 정합성 | 구단별 득점 이벤트 합이 경기 스코어와 일치하는 비율 99.74% (2013~2023 리그). `game_events.club_id`는 득점이 인정된 구단이다(자책골 포함) |
| 출전 구간 모델 검증 | §3.2 규칙(선발/교체 인/교체 아웃/퇴장)으로 계산한 출전 시간이 `minutes_played`와 ±5분 이내인 비율. 2018 시즌 리그 출전 기준으로 탐색 단계에서는 99.996%(교체 인 시각을 알 수 없는 2,855건 제외), 파이프라인 최종 구현에서는 **99.989%**(109,855 / 109,867, 제외 없음)이다. 보고서는 파이프라인 수치를 쓴다 |
| 포지션 분포 | Attack 13,502 / Defender 15,961 / Goalkeeper 5,828 / Midfield 14,272 / Missing 586 |
| 백테스트 가능성 | 2018-07 이전 출전 기록이 있는 2018-07 기준 21세 이하 선수 1,005명 중 이후 시장가치 €50M 이상 도달 47명(FW 22, DF 14, MF 10, GK 1) |
| 참조 무결성 | 경기 홈/원정 구단 중 2,481개가 clubs.csv에 없다. 출전·이벤트·라인업·이적·시장가치 참조까지 합치면 stub 구단은 **17,923개**다(파이프라인 실측). 라인업 315,555행은 players.csv에 없는 선수라 제외한다. 라인업 (game_id, player_id) 중복 12건은 선발 행을 우선해 1건만 남긴다. 키 140cm 미만 13건은 NULL로 바꾼다 |

**포지션별 지표**: 수비수와 골키퍼는 이벤트 기반 출전 구간으로 **출전 중 실점/90, 무실점 선발 비율, 출전 중 득실차/90**을 계산할 수 있다(검증 완료). 태클, 인터셉트, 패스, 선방, xG는 데이터에 **없다**. 이 한계는 보고서 Limitation에 명시한다.

## 2. 저장소 구조와 파일 소유권

에이전트는 자기 소유 경로만 수정한다. 다른 경로는 읽기만 한다. **git commit 금지**(coordinator가 커밋한다).

| 경로 | 소유자 | 내용 |
|---|---|---|
| `db/*.sql`, `scouting/db.py`, `docs/CONTRACT.md`, `README.md`, `requirements.txt`, `.gitignore` | coordinator | 계약 |
| `pipeline/`, `scripts/`, `tests/pipeline/` | **PipelineAgent** | 다운로드, 적재, 파생 계산 |
| `scouting/`(db.py 제외), `tests/app/` | **AppAgent** | 서비스 계층, 추천, 백테스트, CLI |
| `bench/` | **BenchAgent** | 성능 실험, 백테스트 실험, 프로파일링, 그래프 |
| `report/` | ReportAgent(후속) | 6페이지 보고서 |
| `data/` | (gitignore) | 원천 파일, DB 파일 |

## 3. 데이터 적재·파생 규칙 (PipelineAgent)

### 3.1 원천 적재 (`pipeline/load.py`)

- 원천: `https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfermarkt-datasets.zip`
  - sha256 `ae2270f7820e09329c423a12562f4494e237d0dc1a4624cff21df050e79d5a18`
  - 압축을 풀면 `data/raw/tm/*.csv.gz`. 파일이 이미 있고 해시가 맞으면 다운로드를 건너뛴다.
- 빈 문자열은 NULL로 바꾼다. 날짜는 앞 10자(`YYYY-MM-DD`)만 쓴다.
- `competition`: 65행 전부 적재한다.
  - `is_covered=1`: §1의 14개 리그
  - `is_big5=1`: GB1, ES1, IT1, L1, FR1
  - `is_uefa_club=1`: CL, EL
- `club`: clubs.csv를 먼저 적재한다. 이어서 games(홈/원정 구단 이름), appearances, lineups, events, transfers(from/to 구단 이름), players.current_club_id, valuations에서 참조만 되는 구단을 `is_stub=1`로 추가한다. 이름을 모르면 `'Unknown club <id>'`.
- `player`: 키 10 미만 또는 220 초과 값은 NULL로 바꾼다. position은 원문 그대로 둔다(`pos_group`은 생성 컬럼).
- `appearance`: players에 없는 선수 2행은 제외한다. 컬럼 매핑: `player_club_id` → `club_id`.
- `game_lineup`: players나 games에 없는 행은 제외한다. 중복은 starting_lineup 행을 우선한다. `is_starter = (type = 'starting_lineup')`.
- `game_event`: 전부 적재한다(선수 FK 없음). `is_sending_off = type='Cards' AND (description LIKE 'Red card%' OR description LIKE 'Second yellow%')`.
- `transfer`: `transfer_fee` → `fee_eur`. 날짜는 미래 값도 원문 그대로 유지한다.
- 테이블마다 트랜잭션 하나, `executemany`로 넣는다. 적재 후 `PRAGMA foreign_key_check` 결과가 0행이어야 한다.
- 원천 행 수, 적재 행 수, 제외 사유별 건수를 `data/load_report.json`에 기록한다.

### 3.2 시즌 사실 `player_season` (`pipeline/derive.py`)

- **대상**: covered 리그(`is_covered=1`) 경기, 2012~2025 시즌. 리그 출전 시간이 1분 이상인 (선수, 시즌). 생년월일이 NULL이거나 position이 'Missing'인 선수는 제외한다.
- `age` = `CAST((julianday(season||'-07-01') - julianday(date_of_birth)) / 365.25 AS INTEGER)`. 14~45 밖이면 제외한다.
- `main_club_id`: 리그 출전 시간이 최대인 구단. 동률이면 출전 수가 많은 쪽, 그다음 club_id가 작은 쪽.
- `team_league_games`: main_club의 해당 시즌 covered 리그 경기 수.
- **선발 판정**: 해당 (경기, 선수)의 라인업 행이 있으면 `is_starter`를 쓴다. 없으면(2012 시즌 등) "그 경기에 교체 인 이벤트가 없음"을 선발로 본다.
- **출전 구간** `(in, out]`:
  - `in` = 0(선발) 또는 `MIN(minute)`(Substitutions에서 `player_in_id`가 해당 선수인 이벤트)
  - `out` = MIN(교체 아웃 minute(Substitutions의 `player_id`), 퇴장 minute(`is_sending_off=1`)). 둘 다 없으면 ∞.
  - 득점 이벤트 minute `m`이 `in < m ≤ out`이면 출전 중 득점으로 본다.
  - `m = -1`(분 정보 없음)은 `in=0`이고 `out=∞`인 선수에게만 센다.
  - 이벤트의 `club_id`가 출전 구단이면 `onpitch_gf`, 상대 구단이면 `onpitch_ga`에 더한다. 출전 구단이 경기의 홈/원정 어느 쪽도 아니면 그 출전은 on-pitch 집계에서 빼고 건수를 기록한다.
- `clean_sheets`: 선발이고, `out=∞`이고, 출전 중 실점이 0인 경기 수.
- `goals`, `assists`, `yellow_cards`, `red_cards`, `league_*`: covered 리그 경기만 센다.
- `uefa_minutes`: 같은 시즌 CL, EL 경기 출전 시간 합.
- `competition_season_strength`: covered 리그 × 시즌별로, 그 시즌 리그에 출전한 선수들의 `season-07-01` **이전** 최신 시장가치 평균. 시장가치가 없는 선수는 제외한다.
- `comp_strength_eur`: 선수가 그 시즌 뛴 covered 리그들의 strength를 출전 시간으로 가중 평균한 값.
- `player_season_metric`: `db/reference_data.sql`의 `metric.description` 공식대로 계산한다.
  - `league_minutes < metric.min_minutes`이면 행을 만들지 않는다.
  - `clean_sheet_rate`는 `league_starts > 0`일 때만 만든다.
  - `minutes_share`, `start_rate`는 1로 상한한다.

### 3.3 스냅샷 (`pipeline/derive.py`)

- `snapshot.as_of_date` **미만** 데이터만 그 스냅샷에서 보인다. 시즌 s는 `date((s+1)||'-06-30') < as_of_date`일 때만 포함한다(= `v_player_season_asof`).
- 기본 스냅샷: `current` = `2026-07-07`, `bt2018` = `2018-07-01`. 벤치는 `bt2019`, `bt2020`을 추가로 만들 수 있다.
- `cohort_baseline`: 스냅샷에 포함된 `player_season_metric`을 `(pos_group, age, metric_code)`로 묶어 mean, 모표준편차, n을 구한다. 나이는 16~35만.
- `player_season_z`: `n ≥ 20`이고 `std > 0`인 코호트만 계산한다.
  - `z = (value - mean) / std`
  - `higher_is_better = 0`이면 부호를 뒤집는다.
  - [-4, 4]로 자른다.
- `world_class_label`: pos_group이 있는 모든 선수 × 모든 정의에 행을 만든다(0 또는 1).
  - `peak_value`: as_of 이전 시장가치가 임계값 이상(GK는 `gk_value_threshold_eur`)인 최초 날짜를 `achieved_on`으로 한다.
  - `big5_regular`: 포함 시즌 중 big5 리그 출전 시간이 `min_league_minutes` 이상인 시즌이 `min_seasons`개 이상이고, as_of 이전 CL 출전 시간 합이 `min_cl_minutes` 이상이어야 한다. 두 조건이 처음 충족된 시즌의 `(s+1)-06-30`을 `achieved_on`으로 한다.
- `build_snapshot`은 하나의 트랜잭션에서 기존 행을 지우고 다시 계산한 뒤 `built_at`을 갱신한다.

## 4. 추천·백테스트 규칙 (AppAgent)

- **기준 시즌** `L`: 스냅샷에 포함된 최대 시즌(`v_player_season_asof`).
- **후보**: 시즌 L의 `player_season`에서 아래 조건을 모두 만족하는 선수.
  - `pos_group = P`
  - `league_minutes ≥ min_minutes`
  - as_of 기준 나이(`v_player_age_asof`) ≤ `max_age`
  - 해당 스냅샷·정의의 라벨이 `is_world_class = 0`
- **method별 점수**
  - `random`: 후보를 player_id 순으로 정렬한 뒤 `random.Random(seed).shuffle`. 셔플 순서가 곧 순위다. score = 0.
  - `market_value`: `v_latest_value_asof` 내림차순. 값이 없는 후보는 score 0.
  - `similarity`
    - 후보 벡터 = (snapshot, 선수, L)의 `player_season_z` 중 `metric_weight(P)`에 있는 지표.
    - 비교 풀 = 같은 스냅샷, `pos_group = P`, 후보의 시즌 L 나이와 같은 나이, `season ≤ L − pool_lag_seasons`, 후보 본인 제외.
    - 거리 `d = sqrt(Σ w·(z_c − z_p)² / Σ w)`. 공유 지표의 가중치 합이 **후보가 가진 지표**의 가중치 합의 60% 미만이면 비교하지 않는다. 정렬과 k명 선정은 SQL에서 d²로 하고, sqrt는 Python에서 취한다(SQLite 빌드에 따라 수학 함수가 없을 수 있음). 이웃이 한 명도 없는 후보는 similarity 순위에서 제외한다.
    - 거리 오름차순(동률이면 player_id 오름차순)으로 k명을 뽑는다.
    - `score = Σ is_wc·1/(d+0.1) / Σ 1/(d+0.1)`. is_wc는 해당 스냅샷 라벨이다.
    - `wc_neighbors` = k명 중 월클 수.
    - **거리 계산과 이웃 선정은 SQL 하나**(CTE + GROUP BY + 윈도 함수)로 한다.
  - `hybrid`: `0.5·PERCENT_RANK(similarity score) + 0.5·PERCENT_RANK(market value)`. 시장가치나 이웃이 없으면 해당 항을 0으로 둔다.
- **정렬과 저장**: score 내림차순, player_id 오름차순으로 상위 `top_n`을 `recommendation_item`에 저장한다. similarity와 hybrid는 각 항목의 이웃 k명을 `recommendation_evidence`에 저장한다. run + item + evidence는 **하나의 트랜잭션**으로 쓴다.
- **백테스트**: 정답 = outcome 스냅샷(기본 `current`)에서 같은 정의의 `is_world_class = 1`.
  - `hits@k` = 순위 k 이내 정답 수
  - `precision = hits/k`
  - `recall = hits / (후보 중 정답 수)`. 정답 수가 0이면 NULL.
  - `k ≤ top_n`이어야 한다. 백테스트 run은 `top_n = 50`.

## 5. 기본 파라미터

| 파라미터 | 기본값 |
|---|---|
| max_age | 21 |
| min_minutes | 900 |
| k | 25 |
| pool_lag_seasons | 3 |
| top_n | 20 (백테스트 50) |
| seed | 42 |
| k_eval | (20, 50) |

## 6. Python API (시그니처 고정)

모든 함수의 첫 인자는 `conn: sqlite3.Connection`(`scouting.db.connect()`로 얻은 연결)이다. 쓰기는 `scouting.db.transaction(conn)`으로 감싼다. **SQL 값은 전부 `?` 바인딩으로 넣고, f-string으로 값을 끼워 넣지 않는다**(식별자 화이트리스트는 예외).

### 6.1 `scouting/db.py` (coordinator, 작성 완료)
`connect(path=None)`, `transaction(conn)`(중첩 시 SAVEPOINT), `apply_sql(conn, files=SQL_FILES)`, `db_path(path=None)`, `DEFAULT_DB_PATH`

### 6.2 `pipeline/` (PipelineAgent)
```python
pipeline.download.ensure_dataset(raw_dir: Path = Path("data/raw")) -> Path            # tm/ 디렉터리 반환
pipeline.load.load_all(conn, tm_dir: Path) -> dict[str, dict]                           # load_report 내용
pipeline.derive.build_competition_strength(conn) -> int
pipeline.derive.build_player_season(conn, seasons: Sequence[int] | None = None) -> int  # None=전체, 지정 시 해당 시즌만 삭제 후 재계산(metric 포함)
pipeline.derive.create_snapshot(conn, name: str, as_of_date: str) -> int               # 이름이 이미 있으면 기존 id 반환(as_of 다르면 ValueError)
pipeline.derive.build_snapshot(conn, snapshot_id: int) -> dict                         # baseline, z, label 전부
pipeline.derive.build_labels(conn, snapshot_id: int, def_id: int | None = None) -> int # 정의 수정 후 재계산용
```
`scripts/setup_db.py [--db PATH] [--raw data/raw] [--force]`: 빈 DB 생성(`apply_sql`) → 다운로드 → 적재 → 파생 → 기본 스냅샷 2개 빌드. 각 단계 소요 시간을 출력한다.

### 6.3 `scouting/` (AppAgent)
```python
# services/users.py
register(conn, username, password, role="scout") -> int
authenticate(conn, username, password) -> User | None      # User: dataclass(user_id, username, role)
set_role(conn, actor: User, target_user_id, role) -> None  # admin만
# services/players.py
search_players(conn, *, name=None, pos_group=None, max_age=None, competition_id=None, limit=20, offset=0) -> list[dict]
player_card(conn, player_id) -> dict | None
season_history(conn, player_id) -> list[dict]             # player_season + metric 값(wide)
valuation_history(conn, player_id) -> list[dict]
cohort_percentiles(conn, snapshot_id, player_id, season) -> list[dict]   # metric_code, name_ko, value, percentile(0~100), cohort_n
similar_players(conn, snapshot_id, player_id, season, k=10, def_id=None) -> list[dict]   # def_id 지정 시 이웃의 월클 여부 표시
# services/watchlist.py / services/notes.py  — 모든 수정·삭제는 WHERE ... AND user_id = ? 로 소유권 강제
add_to_watchlist / list_watchlist / update_watch_memo / remove_from_watchlist
create_note / list_notes_for_player / list_my_notes / update_note / delete_note
# services/recommend.py
candidate_ids(conn, *, snapshot_id, def_id, pos_group, max_age, min_minutes) -> list[int]
run_recommendation(conn, *, user_id, snapshot_id, def_id, pos_group, method, max_age=21, min_minutes=900,
                   k=25, pool_lag_seasons=3, top_n=20, seed=42) -> int   # run_id
breakout_prospects(conn, *, snapshot_id, def_id, pos_group, metric_code="minutes_share", max_age=21,
                   mode="all") -> list[dict]
# 시즌 L의 후보 중 같은 나이 시점 월클 선수들의 metric 값과 비교한다.
#   mode="all":  값 > ALL(월클 값)   — 그 나이의 모든 월클보다 높음
#   mode="some": 값 > SOME(월클 값)  — 적어도 한 명의 월클보다 높음
# SQLite는 ALL/SOME/ANY를 지원하지 않는다. x > ALL(S)는 NOT EXISTS(S 중 s >= x), x > SOME(S)는 EXISTS(S 중 s < x)로
# 재작성하고, 코드 주석에 원래 ALL/SOME 형태를 함께 적는다(수업 P3 집합 비교, 보고서 소재).
# S가 비면 ALL은 참이 되므로, 비교 대상 월클이 0명이면 결과를 비우고 이유를 알린다.
# services/backtest.py
evaluate_run(conn, run_id, *, outcome_snapshot_id, k_values=(20, 50)) -> list[dict]
# evaluate_run: outcome 스냅샷의 as_of가 run 스냅샷보다 늦지 않으면 ValueError.
# 권한 모델: actor 인자가 있는 함수만 서비스 계층에서 권한을 검사한다(actor는 필수, None 불가).
# actor가 없는 조회·계산 함수(get_run, run_items, evaluate_run 등)는 신뢰된 호출자(CLI, bench)용 내부 API다.
# 화면 노출 범위(본인 run만, 백테스트는 admin 메뉴)는 CLI가 강제한다.
# services/admin.py
data_status(conn) -> dict
create_definition / update_definition / delete_definition   # (conn, actor: User, ...) admin만. 수정 시 pipeline.derive.build_labels 호출
rebuild_snapshot(conn, snapshot_id, *, actor: User) -> dict  # admin만. pipeline.derive.build_snapshot 위임
```
비밀번호 해시: `hashlib.pbkdf2_hmac('sha256', ..., iterations=200_000)`, 형식은 `pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>`.

## 7. CLI (`python -m scouting [--db PATH]`)

```
메인: 1 로그인 / 2 회원가입(scout) / 0 종료
스카우트:
  1 선수 검색 (이름·포지션군·나이·리그)
  2 선수 프로필 (시즌별 성장표, 시장가치 추이, 동나이대 백분위)
  3 유사 선수 Top-k
  4 다음 월클 추천 실행 (스냅샷·정의·포지션군·method 선택)
  5 내 추천 기록 / 결과 상세
  6 워치리스트 (조회·추가·메모 수정·삭제)
  7 스카우팅 노트 (작성·조회·수정·삭제)
  8 기준 돌파 유망주 (같은 나이 월클과 > ALL / > SOME 비교)
  0 로그아웃
관리자(스카우트 메뉴 + ):
  9 데이터 현황 (테이블 행 수, 스냅샷 목록·빌드 시각)
  10 스냅샷 재계산
  11 월클 정의 관리 (추가·수정·삭제)
  12 백테스트 실행 (run 선택 → precision/recall)
  13 사용자 역할 변경
```
- 관리자 생성: `python -m scouting create-admin <username> --password <pw>`
- `--db` 경로 오류, 디렉터리, 손상 파일, 잠긴 DB도 traceback 없이 한국어 메시지와 종료 코드 1로 끝낸다.
- 잘못된 입력(숫자 아님, 없는 ID, 범위 밖)은 메시지를 출력하고 다시 묻는다. `sqlite3.IntegrityError`는 사용자용 한국어 메시지로 바꾼다. 어떤 입력에도 traceback을 내고 종료하지 않는다(R-48).
- 표 출력은 고정폭 정렬. 예시 보고서 형식(P4 s9)을 따른다.

## 8. 벤치마크 명세 (BenchAgent)

- **구성**
  - B1 = 원천 경로, 보조 인덱스 없음: `data/bench_b1.sqlite`(메인 DB 복사본에서 `ix_` 인덱스를 모두 DROP)에서 원천 테이블을 매번 집계
  - B2 = 원천 경로, 보조 인덱스 있음: 메인 DB에서 원천 테이블을 매번 집계
  - P = 제안 방식: 메인 DB의 파생 테이블(`player_season`, `player_season_metric`, `player_season_z`) + 인덱스
- **질의**: 고정 표본 20명(seed 42, 포지션군별 5명, 시즌 L에 900분 이상)
  - Q1 시즌별 성장표
  - Q2 동나이대 백분위
  - Q3 유사 선수 k-NN (k=10)
- **원천 경로**: `bench/raw_queries.py`에서 §3.2 공식을 CTE로 직접 계산한다. 같은 입력에 대해 P와 결과가 같아야 한다(지표 오차 1e-9 이하, 이웃 ID 동일). 불일치하면 실험을 무효로 본다.
- **측정**: 워밍업 3회 + 측정 30회. median과 p95(ms). `EXPLAIN QUERY PLAN` 결과를 `bench/results/explain/<Q>_<config>.txt`에 저장한다.
- **갱신 비용**: `build_player_season` 전체 vs 1시즌, `build_snapshot` 소요 시간, DB 파일 크기(인덱스 유무 차이).
- **프로파일링(R-19)**: `cProfile`로 similarity 추천 1회(P)와 Q3 원천 경로 1회를 측정해 상위 25개 함수를 `bench/results/profile_*.txt`에 저장한다.
- **백테스트 실험**: 스냅샷 bt2018(+ bt2019, bt2020) × 포지션군 4 × 정의 2 × method 4, `top_n = 50`, outcome은 `current`, k = 20, 50. random은 seed 10개 평균.
- **산출물**
  - `bench/results/query_latency.csv`: `query, config, player_id, run, ms`
  - `bench/results/query_summary.csv`: `query, config, median_ms, p95_ms, speedup_vs_b1`
  - `bench/results/refresh.csv`
  - `bench/results/backtest.csv`: `snapshot, pos_group, def_code, method, k, n_candidates, n_positive, hits, precision, recall`
  - `bench/results/env.json`: CPU, OS, Python, SQLite 버전, DB 크기, 테이블 행 수
  - `bench/results/figures/*.png`
  - `bench/results/SUMMARY.md`: 보고서 작성자용 수치 요약과 해석
- 실행: `python bench/run_all.py [--quick]`. `--quick`은 반복 5회, 스냅샷 bt2018만.

## 9. 재현 명령

```bash
pip install -r requirements.txt
python scripts/setup_db.py                 # 다운로드~스냅샷 빌드
python -m scouting create-admin admin --password admin1234
python -m scouting                         # CLI
python -m pytest                           # tests/pipeline, tests/app
python bench/run_all.py                    # 실험 재현
```

## 10. 완료 기준

| 에이전트 | 완료 증거 |
|---|---|
| Pipeline | `scripts/setup_db.py`를 빈 상태에서 끝까지 실행한 로그. `load_report.json`. `foreign_key_check` 0행. §1의 99.996% 출전 구간 검증을 `tests/pipeline`에서 재현(합성 경기 + 실데이터 표본). 스냅샷 2개 `built_at` NOT NULL |
| App | `pytest tests/app` 통과. 다음을 테스트로 증명한다: 타인 노트·워치리스트 수정/삭제 거부, 추천 실행 중 예외 시 run·item 롤백, bt2018 추천이 2018-07-01 이후 데이터에 의존하지 않음(이후 데이터 변조 전후 결과 동일), 잘못된 CLI 입력에서 종료하지 않음. 실데이터로 4개 method 실행 로그 |
| Bench | `run_all.py` 전체 실행 로그. §8 산출물 전부. 원천 경로와 P 결과 일치 검증 로그 |

최종 검증: fable5.2가 [REQUIREMENTS.md](./REQUIREMENTS.md) §6 체크리스트로 판정한다.
