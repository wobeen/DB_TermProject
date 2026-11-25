# 다음 할 일

작업 현황과 남은 일을 기록한다. 마지막 갱신: 2026-11-26.

## 현재 상태
- **서비스**
  - CLI(`python -m scouting`): 스카우팅 전체 기능(검색, 프로필, 유사 선수, 추천 4방식, 백테스트, 워치리스트, 노트, 기준 돌파 `> ALL`/`> SOME`, 관리자)
  - GUI(`python -m scouting.gui`): 읽기 전용 선수 커리어 탐색기
- **테스트**: `python -m pytest -q` 전체 통과(마지막 전체 실행 152개, 이후 GUI 회귀 테스트 1개 추가로 GUI 56개 통과)
- **실험**: `bench/results/SUMMARY.md`
  - 파생 계층이 원천 집계보다 16~6,237배 빠르고, 원천 집계와 결과가 같다.
  - 백테스트에서 시장가치 순위를 넘지 못했다.
- **보고서**: `report/report.pdf` (영어, A4 6페이지)
- **저장소**: https://github.com/wobeen/DB_TermProject (공개)

## 제출 전에 꼭 할 일
1. **보고서에 이름·학번 넣기**
   - `report/report.md` 제목 아래 줄에 넣는다.
   - `python report/build.py`를 실행한다. Word가 필요하다.
   - 출력되는 `PDF pages:`가 **6**인지 확인한다. 마지막 페이지가 약 83% 차 있어 한두 줄 여유가 있다.
   - Word로 직접 고치면 `report.md`에는 반영되지 않는다. 그 뒤 `build.py`를 실행하면 Word에서 고친 내용이 덮어써진다.
2. **제출 방식 확인**: 강의자료(1~4번 PPT)에는 마감, 파일 형식, 제출 경로, 코드 제출 여부가 없다. e-class 공지나 조교 안내를 확인한다.
   - 보고서만 내면 `report/report.pdf`를 낸다.
   - 코드도 내면 GitHub 링크(공개됨)를 내거나, `data/`를 뺀 압축 파일을 낸다.
3. **처음부터 재현 확인(R-47)**: 새 폴더에서 README 순서대로 끝까지 실행한 적이 아직 없다.
   ```bash
   git clone https://github.com/wobeen/DB_TermProject.git && cd DB_TermProject
   pip install -r requirements.txt
   python scripts/setup_db.py          # 약 9분, 디스크 약 1.3GB
   python -m scouting create-admin admin --password admin1234
   python -m scouting.gui              # GUI
   python -m scouting                  # CLI
   python -m pytest -q
   ```
   백테스트 스냅샷 `bt2019`, `bt2020`은 `python bench/run_all.py`(약 50분)가 추가한다.

## 선택 사항 (시간이 남으면)
- **보고서 ER 다이어그램이 작다**(페이지 폭의 약 58%). 인쇄해서 읽기 어려우면 다른 문단을 줄이고 키운다.
- **시연 준비**(발표가 있으면)
  - GUI: 손흥민 검색 → 커리어(이적 이력, 커리어 경로, 시장가치 툴팁)
  - CLI: 메뉴 4 추천(10초 안팎 걸림) → 메뉴 8 기준 돌파 유망주
- **실제 출전 포지션 기준 검색**: 지금 GUI의 포지션 검색은 선수의 **등록 주 포지션** 하나만 본다. `game_lineup.position`을 선수별로 집계한 테이블을 추가하면 실제로 뛴 포지션으로도 찾을 수 있다.
- **GUI 정렬**: 결과 표 머리글을 눌러 정렬하는 기능은 아직 없다.
- **교차 리뷰 범위**: `docs/reviews/review_pipeline_app.md`는 GUI를 만들기 전의 코드만 다룬다. GUI 코드는 테스트와 화면 점검만 거쳤다.

## 알려진 데이터 한계
- **수집 범위**: 원본(Transfermarkt 데이터셋)은 2026-07-06에 수집이 멈췄다. 2026/27 시즌과 그 뒤 이적은 없다.
- **수록 대회**: 출전 기록은 유럽 1부 14개 리그, 국내컵, UEFA 대회, 주요 국가대항전만 있다(2012/13 시즌부터). MLS, K리그 등은 없다.
- **누락 사례**
  - 이적 기록이 없는 선수가 있다(예: 앤디 캐럴). 이런 선수의 재직 기간은 출전 기록으로 추정하고 `(2012/13 이전 미수록)`을 붙인다.
  - 시즌 기록이 빠진 경우가 있다(예: 오블락 2014/15).
- **지표**: 태클, 패스, 선방, xG는 없다. 수비수와 골키퍼는 출전 중 실점과 무실점 기반으로만 평가한다.

## 설치된 디자인 스킬 (참고)
- `~/.claude/skills/frontend-design`: Anthropic 공식. 자동 호출 꺼짐.
- `~/.claude/skills/ui-ux-pro-max`: 커밋 `281e4537`을 보안 검증한 뒤 설치. 개발용 테스트 폴더는 제외했다.
- taste-skill, impeccable: 검증 결과 주의 등급이고 Tkinter GUI에 쓸 수 없어 설치하지 않았다(사용자 결정).
