# 축구 유망주 스카우팅 DB — "다음 월드클래스" 추천

DB 텀프로젝트. 선수들의 시즌별 성장 기록을 SQLite에 쌓는다. 같은 나이 시점의 기록으로 월드클래스가 된 선수와 현재 유망주를 비교해 다음 월드클래스 후보를 추천하는 CLI 서비스다.

- DB: SQLite ≥ 3.37 (STRICT 테이블), 단일 파일 `data/scouting.sqlite`
- 언어: Python ≥ 3.11, 런타임은 표준 라이브러리만 사용
- 데이터: [Transfermarkt datasets](https://github.com/dcaribou/transfermarkt-datasets) (CC0), 2026-07-06 스냅샷

## 빠른 시작

```bash
pip install -r requirements.txt                       # pytest, matplotlib (테스트·벤치용)
python scripts/setup_db.py                            # 다운로드 → 적재 → 파생 계산 → 스냅샷 2개 (약 8~9분)
python -m scouting create-admin admin --password admin1234
python -m scouting                                    # CLI (한국어 메뉴)
```

- `setup_db.py` 옵션: `--db PATH`, `--raw data/raw`, `--force`(기존 DB를 지우고 다시 만듦). 원천 zip(약 240MB)은 sha256을 확인하고 이미 있으면 다시 받지 않는다. 적재 결과는 `data/load_report.json`에 남는다.
- `python -m scouting --db PATH`로 다른 DB 파일을 지정할 수 있다.

## CLI 메뉴

| 구분 | 메뉴 |
|---|---|
| 메인 | 로그인, 회원가입, 종료 |
| 스카우트 | 1 선수 검색 / 2 선수 프로필(성장표·시장가치·동나이대 백분위) / 3 유사 선수 Top-k / 4 다음 월클 추천(random·market_value·similarity·hybrid) / 5 내 추천 기록 / 6 워치리스트 / 7 스카우팅 노트 / 8 기준 돌파 유망주(`> ALL` / `> SOME`) |
| 관리자 | 9 데이터 현황 / 10 스냅샷 재계산 / 11 월클 정의 관리 / 12 백테스트 / 13 사용자 역할 변경 |

## 테스트와 실험

```bash
python -m pytest -q          # tests/pipeline + tests/app (실DB 테스트는 DB가 없거나 잠겨 있으면 skip)
python bench/run_all.py      # 질의 성능 B1/B2/P, 갱신 비용, cProfile, 백테스트 (약 50분)
python bench/run_all.py --quick
```

실험 결과와 해석은 `bench/results/SUMMARY.md`에 있다. 원본 수치는 `bench/results/*.csv`, 실행 계획은 `explain/`, 그래프는 `figures/`에 있다.

## 보고서

`report/report.pdf` (영어, A4 6페이지). 빌드 방법은 [report/README.md](report/README.md)에 있다.

## 저장소 구조

| 경로 | 내용 |
|---|---|
| `docs/REQUIREMENTS.md` | 강의자료 기반 요구사항과 최종 검증 체크리스트(R-ID) |
| `docs/PLANS.md` | 기획안 후보와 선정 이유(기획안 E) |
| `docs/CONTRACT.md` | 데이터 검증 결과, 적재·파생 공식, 추천·백테스트 규칙, API, CLI, 벤치 명세 |
| `docs/reviews/` | 교차 리뷰 결과 |
| `db/` | `schema.sql`, `views.sql`, `indexes.sql`, `reference_data.sql` |
| `pipeline/`, `scripts/` | 다운로드, 적재, 파생 계산, `setup_db.py` |
| `scouting/` | DB 연결(`db.py`), 서비스 계층(`services/`), CLI(`cli/`) |
| `tests/` | `pipeline/`, `app/` |
| `bench/` | 성능·백테스트 실험과 결과 |
| `report/` | 보고서 원문, 빌드 스크립트, 그림, CLI 출력 기록 |
