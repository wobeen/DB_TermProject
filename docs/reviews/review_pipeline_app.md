# 교차 리뷰: pipeline / scripts / scouting (Claude → GPT 코드)

검토 대상: `pipeline/*.py`, `scripts/setup_db.py`, `scouting/services/*`, `scouting/cli/*`, `tests/`. 기준: `docs/CONTRACT.md` §3·§4·§6, `docs/REQUIREMENTS.md`.
코드는 수정하지 않았다. `scouting/cli/*`와 `services/players.py`는 AppAgent가 수정 중이라 **내가 읽은 시점의 파일** 기준이다.

## 요약

- Blocker 0건, Major 3건, Minor 6건.
- 계약 §3(출전 구간, clean sheet, as_of 경계, z 부호/클리핑, 라벨)과 §4(후보, 60% 규칙, pool_lag, 점수식, 정렬)는 코드와 일치한다.
- 값이 f-string이나 문자열 연결로 SQL에 들어가는 곳은 없다.
- 실행 결과:
  - `python -m pytest -q`: 61 passed, 1 failed. 실패는 `tests/pipeline/test_real_data.py`의 `sqlite3.OperationalError: database is locked`다. 다른 에이전트(Bench)가 `data/scouting.sqlite`를 쓰는 중이었고, 코드 결함이 아니라 환경 경합이다. 단독 재실행에서도 같은 이유로 3건 실패했다.
  - 실DB: 락 때문에 추천 run을 저장(쓰기)하지 않았다. 대신 읽기 전용 연결로 추천 계산 경로(`candidate_ids` + `knn` + 점수식)를 실행했다.

```
bt2018 L 2017 DF cands 112 with_nb 112 top3 [(256178, 0.24), (258004, 0.202), (339808, 0.159)]
bt2018 L 2017 FW cands  76 with_nb  76 top3 [(351478, 0.296), (396894, 0.26), (341092, 0.183)]
current L 2025 DF cands 107 with_nb 107 top3 [(924117, 0.388), (1121298, 0.322), (935480, 0.287)]
current L 2025 FW cands  84 with_nb  84 top3 [(930781, 0.606), (1185888, 0.563), (748804, 0.558)]
bt2018 z seasons>2017: 0
bt2018 labels achieved_on>=as_of: 0
PRAGMA foreign_key_check: []
```
  스크립트는 scratchpad의 `real.py`이고, 쓰기는 없다.

## 이슈 목록

### Major

**M1. CLI가 `--db` 문제와 DB 오류에서 traceback으로 종료한다 (R-48)**
- 위치: `scouting/cli/main.py:631-633`(`dbm.connect`, `_ensure_schema`는 `try`/`safe` 밖), `scouting/db.py:32`.
- 증거(실행):
  - `python -m scouting --db /nonexistent_dir/x.sqlite` → `sqlite3.OperationalError: unable to open database file` (traceback)
  - `--db <디렉터리>` → 같은 traceback
  - `--db <텍스트 파일>` → `sqlite3.DatabaseError: file is not a database` (traceback, `_ensure_schema`에서 발생)
  - DB가 잠긴 채 시작해도 `_ensure_schema`의 쿼리가 같은 경로로 새어 나올 수 있다.
- 메뉴 안의 입력은 `App.safe`가 전부 잡지만, 진입부는 보호가 없다. 계약 §7은 "어떤 입력에도 traceback을 내고 종료하지 않는다"이다.
- 제안: `main()`에서 `connect`와 `_ensure_schema`를 `try/except sqlite3.Error`로 감싸 한국어 메시지(예: "DB 파일을 열 수 없습니다: 경로 확인")를 출력하고 종료 코드 1을 반환한다.

**M2. `rebuild_snapshot`이 `actor=None`이면 관리자 검사를 건너뛴다 (R-42, §6.3)**
- 위치: `scouting/services/admin.py:102-105`.
- 계약 시그니처는 `rebuild_snapshot(conn, snapshot_id, *, actor: User)`(필수)이고 "admin만"이다. 구현은 `actor: User | None = None`이고 `if actor is not None:`일 때만 검사한다. 인자를 생략하면 권한 없이 전체 스냅샷 재빌드가 실행된다(z·라벨 삭제 후 재계산).
- CLI는 항상 `actor`를 넘기므로 지금 UI 경로로는 악용되지 않는다. 서비스 계층 API가 우회 가능하다는 점이 문제다.
- 제안: `actor`를 필수 키워드 인자로 바꾸고 항상 `require_admin`을 호출한다. 테스트에는 `actor` 생략 시 TypeError 또는 PermissionError를 단언한다.

**M3. 핵심 추천 경로의 테스트 공백 (테스트 품질)**
- 위치: `tests/app/test_services.py::test_methods_market_value_random_hybrid`(약 245-262행).
- `hybrid`는 `len == 3`, `0 <= score <= 1`, evidence 존재만 확인한다. `0.5·PERCENT_RANK(sim) + 0.5·PERCENT_RANK(value)` 식, 값이 없는 후보의 0 처리, 이웃이 없는 후보 처리는 검증하지 않는다. 식이 틀려도 통과한다.
- `random`은 같은 seed의 재현성(`r1 == r2`)과 원소 집합만 본다. 계약의 "player_id 정렬 → `Random(seed).shuffle`" 순서를 기대값으로 비교하지 않는다. 정렬 단계를 빼도 통과한다.
- `top_n` 절단, `market_value`의 동점(player_id 오름차순) 정렬도 없다.
- 누수 테스트(`test_backtest_snapshot_has_no_leakage`)는 파생 테이블(`player_season`, `player_season_z`, `player_valuation`)만 바꾼다. `appearance`, `game_event` 같은 원천 테이블 변경은 다루지 않는다. 추천 코드는 원천을 읽지 않으므로 이 테스트 자체는 유효하다. 대신 파이프라인 쪽에서 `tests/pipeline/test_snapshot.py`가 as_of 경계(`2018-07-01` 당일 제외, 시즌 종료일 경계)를 검증하고 있어 이 공백은 부분적으로 메워져 있다.
- 제안: 합성 데이터로 `hybrid` 기대 점수를 손으로 계산해 비교하고, `random`은 `sorted(ids)` 후 `random.Random(seed).shuffle` 결과와 순서를 직접 비교하며, `top_n < 후보 수`와 동점 정렬 케이스를 추가한다.

### Minor

- **m1. 매우 큰 정수 입력의 메시지**: ID에 `99999999999999999999`를 넣으면 `[예상치 못한 오류] OverflowError: Python int too large to convert to SQLite INTEGER`가 출력된다. traceback은 아니지만 사용자용 메시지가 아니다. 위치: `scouting/cli/ui.py:108-122`(`IO.integer`에 상한이 없다), `main.py` `pick_player`의 `s.isdigit()` 경로. 제안: `integer` 기본 범위를 `1..2**63-1`로 제한하고, `isdigit` 경로에서 `len`이나 값 범위를 검사한다.
- **m2. 백테스트가 outcome 스냅샷의 선후를 검사하지 않는다**: `scouting/services/backtest.py:27-33`. outcome이 run의 스냅샷과 같거나 더 이전이어도 평가된다. 같은 스냅샷이면 후보는 `is_world_class=0`이라 hits가 구조적으로 0이다. 제안: `as_of(outcome) > as_of(run.snapshot)` 아니면 `ValueError`.
- **m3. 서비스 계층의 일부 함수가 호출자 권한을 확인하지 않는다**: `evaluate_run`(백테스트)과 `get_run`/`run_items`/`run_evidence`는 actor나 소유자 인자가 없다. 계약 시그니처가 그렇고, CLI는 메뉴 11을 admin에게만 보이며 `my_runs`에서 본인 run만 선택하게 한다. 그래도 서비스 API만 보면 타인 run의 조회와 백테스트 덮어쓰기(`INSERT OR REPLACE`)가 가능하다. 계약 변경 사항이므로 coordinator 판단이 필요하다.
- **m4. `pipeline/load.py`의 `INSERT OR IGNORE`가 조용히 행을 버린다**: `load.py:193, 216, 240, 292` 등. `INSERT OR IGNORE`로 PK/UNIQUE 충돌 행이 사라지는데, 제외 사유별 건수(§3.1)에 포함되는지는 확인하지 못했다(리포트 집계 코드는 전부 읽지 않았다). `data/load_report.json`에서 원천 행 수 = 적재 행 수 + 제외 행 수가 맞는지 확인하길 권한다.
- **m5. `similar_players`의 `def_id`가 위치 인자가 아니라 키워드 전용이다**: `players.py:162-170`. 계약은 `k=10, def_id=None`을 나열한다. 현 호출부는 키워드로 부르므로 동작에는 문제가 없다. 시그니처 고정 원칙상 차이로 기록한다.
- **m6. 실DB 테스트가 동시 사용에 취약하다**: `tests/pipeline/test_real_data.py`는 락이 걸린 DB에서 3건 모두 `OperationalError`로 실패한다. `skipif`는 파일 존재만 본다. 제안: `connect` 실패(`OperationalError`) 시 `pytest.skip`하거나, 읽기 전용 URI + 재시도로 바꾼다.

## 확인 항목별 결과

### 1. 계약 일치 — 일치

| 항목 | 증거 |
|---|---|
| 출전 구간 `(in, out]`, 선발 0, `in=MIN(minute)`, `out=MIN(교체 아웃, 퇴장)` | `pipeline/derive.py:97-125`(t_ev_in, t_ev_out), `:150-151`, `:165-166`(`minute > inn AND minute <= COALESCE(out, 1000000)`) |
| `m = -1`은 `in=0 AND out=∞`만 | `derive.py:165` |
| 선발 대체 규칙(라인업 없으면 교체 인 이벤트 없음 = 선발) | `derive.py:139-140` |
| 홈/원정이 아닌 출전 구단 제외 + 건수 기록 | `derive.py:142, 163-164, 182` |
| clean sheet = 선발 ∧ `out=∞` ∧ 실점 0 | `derive.py:196` |
| age, 14~45 | `derive.py:257, 266` |
| main_club 동률 규칙 | `derive.py:207-208` |
| strength: `season-07-01` 이전 최신 가치의 평균 | `derive.py:58` |
| as_of 경계 `date((s+1)||'-06-30') < as_of` | `derive.py:371, 396, 435`, `db/views.sql:10` |
| 코호트 나이 16~35, `n≥20`, `std>0`, 모표준편차 | `derive.py:16-17, 371-374, 396` |
| z: `higher_is_better=0`이면 부호 반전, ±4 클리핑 | `derive.py:389-390` |
| 라벨: 모든 pos_group 선수 × 정의, GK 임계값, `achieved_on` | `derive.py:403-456` |
| `build_snapshot` 단일 트랜잭션, `built_at` 갱신 | `derive.py:481-494` |
| 후보 조건(pos, minutes, as_of 나이, 라벨 0) | `scouting/services/recommend.py:15-24` |
| 60% 규칙(정수 비교), 가중 거리, 풀 조건, 정렬, SQL 하나 | `scouting/services/knn.py:15-58` (`sw*10 >= tw*6`, `ORDER BY d2, nb_id, nb_season`) |
| 점수식 `Σ is_wc/(d+0.1) / Σ 1/(d+0.1)` | `recommend.py:95-98` |
| random: `sorted` 후 `Random(seed).shuffle` | `recommend.py:177-180` |
| score 내림차순, player_id 오름차순, top_n | `recommend.py:194-196` |
| run + item + evidence 단일 트랜잭션 | `recommend.py:202-210` |
| precision/recall 정의, `k ≤ top_n` | `backtest.py:32-33, 71-72` |

6절 시그니처: 위 m5와 M2를 제외하고 일치한다.

### 2. 보안·정합성
- f-string/연결 SQL grep 결과(`pipeline`, `scouting`, `scripts`의 `.py`):
  - `derive.py:42`: `DROP TABLE IF EXISTS temp.{t}` — 내부 상수 튜플
  - `load.py:96, 100`: `{table}`, `{col}` — 내부 상수(코드 주석에 명시)
  - `load.py:368`: `PRAGMA synchronous = {int(old_sync)}` — `int()` 변환
  - `db.py:46-54`: SAVEPOINT 이름 — 내부 카운터
  - `admin.py:38`: 테이블 이름 — `STATUS_TABLES` 화이트리스트
  - `admin.py:67, 85`: 컬럼 이름 — `_DEF_FIELDS`로 필터링한 목록, 값은 `?`
  - `knn.py:88`: `.format(cand_sql=...)` — 내부 상수 `CAND_SQL`
  - `players.py:57`: WHERE 조각 — 고정 문자열, 값은 `?` (LIKE는 `ESCAPE` 처리)
  - `recommend.py:76-77`: `IN (?,?,…)` 자리표시자 개수만 조합
  - `recommend.py:220, 235-237`: 고정 SQL + 고정 조각
  - `setup_db.py:115`: 테이블 이름 상수
  - 사용자 입력이 SQL 텍스트로 들어가는 곳은 없다 → **R-41 PASS**.
- 소유권: `watchlist.py:39-53`, `notes.py:48-72` 모두 `WHERE ... AND user_id = ?`로 강제한다. CLI도 사전 확인(`is_watched`, `note_owned`)을 하지만 최종 쿼리가 조건을 다시 건다. `test_notes_ownership`, `test_watchlist_ownership`이 타인 수정·삭제 거부를 증명한다. 소유권이 빠진 수정·삭제는 없다(관리자 기능은 `require_admin`이 DB의 현재 역할로 검사) → **R-42 PASS**, 단 M2와 m3은 별도 지적이다.
- 트랜잭션: 여러 테이블을 쓰는 곳은 `run_recommendation`(run/item/evidence, `recommend.py:202`), `create_definition`/`update_definition`(정의 + 재라벨링, `admin.py:65-71, 83-90`), `build_snapshot`(`derive.py:483`), `build_player_season`(`derive.py:322`)이고 모두 `transaction()` 안이다. 롤백은 `test_run_rolls_back_on_exception`, `test_item_failure_also_rolls_back_run`, `test_definition_update_relabels_and_rolls_back`으로 검증한다. 후보 조회는 트랜잭션 밖에서 읽고 쓰기만 묶는 구조라 일관성에는 문제가 없다 → **R-43 PASS**.
- 무결성: `db/schema.sql`의 CHECK·FK·UNIQUE가 `IntegrityError`를 내고, CLI가 한국어로 번역한다(`main.py:18-32`). 예: 노트 평점 9(`test_note_integrity_errors`), 메모 201자, 중복 워치리스트 → **R-44 PASS** (스키마 자체는 이 리뷰 범위가 아니다).

### 3. 누수 — 없음
- `recommend.py`, `knn.py`, `backtest.py`는 `v_player_season_asof`, `v_player_age_asof`, `v_latest_value_asof`와 `snapshot_id` 키 테이블(`player_season_z`, `world_class_label`)만 읽는다. 원천 테이블(`appearance`, `game_event`, `player_valuation`)을 직접 읽지 않는다.
- 파이프라인: baseline, z, 라벨 모두 `date((season+1)||'-06-30') < as_of`와 `v.date < as_of`를 건다(`derive.py:371, 396, 412, 435`).
- 실DB 확인: `bt2018` 스냅샷에서 `season > 2017`인 z 행 0건, `achieved_on >= '2018-07-01'`인 라벨 0건.
- 표시용 조회는 의도적으로 현재 시점이다(`players.season_history`, `valuation_history`). 계약상 스냅샷 인자가 없다.

### 4. 견고성(R-48)
메뉴 안의 입력(숫자 아님, 범위 밖, 없는 ID, 긴 문자열, EOF)은 처리된다. `test_cli_invalid_input_sequence_reaches_exit`가 재현하고, 내가 큰 정수를 직접 넣어도 traceback은 없었다(m1은 메시지 품질). **진입부에서 traceback이 난다(M1)**. → **R-48 FAIL** (M1 해결 시 PASS).

### 5. 테스트 품질
- 좋은 점: 손계산 kNN 비교(`test_knn_matches_hand_computation`), 60% 경계, pool_lag 경계, as_of 당일 경계, 롤백 주입, 소유권, 파이프라인 출전 구간·clean sheet·z 클리핑 테스트가 모두 의미 있다.
- 문제: M3(hybrid/random 기대값 없음), m6(실DB 테스트 락 취약). 배선만 확인하는 테스트로는 `test_data_status`의 `player == 16`이 합성 데이터 크기에 묶여 있어 취약한 편이다.
- 누락된 경로: `similar_players`(서비스) 단독 테스트, `evaluate_run`의 outcome 선후 검증, `--db` 오류 경로.

### 6. 실행 확인
- `python -m pytest -q`: **61 passed, 1 failed** (실패 = 실DB 락, 위 요약 참조).
- `scouting/cli`와 `players.py`가 수정 중이라, 이 결과는 읽은 시점의 파일 기준이다.
- 실DB 추천 저장(`run_recommendation` 쓰기)은 락 때문에 하지 못했다. 계산 경로는 읽기 전용으로 확인했다(위 출력). 4개 method의 전체 실행 로그는 AppAgent 쪽 완료 증거로 따로 확인이 필요하다.

## R-ID 판정

| R-ID | 판정 | 근거 |
|---|---|---|
| R-05 앱이 코드로 DB 연결 후 SQL 실행 | PASS | `scouting/db.py:26-36`, 전 서비스가 `sqlite3` 연결로 SQL 실행 |
| R-41 바인딩만 사용 | PASS | f-string SQL grep: 값 삽입 0건, 식별자는 화이트리스트 |
| R-42 소유권·권한 | PASS (M2, m3 권고) | `watchlist.py`, `notes.py`의 `AND user_id = ?`, `require_admin` |
| R-43 트랜잭션 | PASS | 다중 테이블 쓰기 전부 `transaction()` + 롤백 테스트 |
| R-44 DB 무결성 | PASS | CHECK/FK/UNIQUE가 IntegrityError, CLI 번역 |
| R-45 JOIN/GROUP BY/서브쿼리/VIEW | PASS | `knn.py`(CTE, JOIN, GROUP BY, 윈도), `views.sql`, `v_latest_value_asof`의 상관 서브쿼리. 단 ALL/SOME 집합 비교는 이 범위에서 보지 못했다 |
| R-46 측정 가능한 개선 기법 | 이 범위 밖 | 벤치(`bench/`) 소관, 확인하지 않았다 |
| R-47 재현성 | 부분 확인 | `scripts/setup_db.py`와 README는 읽지 않았고, 실행하지 않았다 |
| R-48 잘못된 입력에도 죽지 않음 | **FAIL** | M1: `--db` 잘못된 경로/디렉터리/손상 파일에서 traceback |
