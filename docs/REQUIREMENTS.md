# DB 텀프로젝트 기본 요구사항

출처: 폴더 내 강의자료 4개
- `1. Project Introduction.pptx` (P1): 과제 정의, 보고서 구성, MySQL·JDBC 연결
- `2. Project Introduction2.pptx` (P2): SQLite, C 연동
- `3. Executing SQL.pptx` (P3): DB/테이블 생성, `ALL`/`SOME` 집합 비교 서브쿼리
- `4. Project Examples.pptx` (P4): 예시 보고서 3개(수강 장바구니, 항공 예약, 비교과 신청)와 General Advice

표기 규칙
- **MUST**: 강의자료에 명시된 요구. 빠지면 감점 위험.
- **SHOULD**: 예시 보고서와 General Advice가 강조하는 항목.
- **[추론]**: 자료에 명시되진 않았지만 DB 과목 평가에서 통상 기대되는 품질 기준. 팀 판단으로 채택.

각 항목의 ID(`R-xx`)는 최종 검증(fable5.2) 체크리스트에서 그대로 쓴다.

---

## 1. 결과물 구성 (MUST)

| ID | 요구사항 | 근거 |
|---|---|---|
| R-01 | 데이터베이스를 활용하는 **서비스**를 만든다. 예: POS, 수강신청, 고객 서비스 등 | P1 s3 |
| R-02 | 프로그램은 **CLI 또는 GUI**로 동작해야 한다 | P1 s3 |
| R-03 | DBMS는 **MySQL 또는 SQLite** 중 하나를 쓴다 | P1 s3 |
| R-04 | 개발 언어는 자유다(C, Java, Python 등) | P1 s3, P4 s23 "I do not care about Programming model or DB" |
| R-05 | 애플리케이션이 **코드로 DB에 연결**해서 SQL을 실행한다. 예: JDBC `DriverManager.getConnection`, `sqlite3_open`, Python `sqlite3`/`pymysql` | P1 s36–44, P2 s15 |
| R-06 | **보고서**: 프로젝트 설명, DB 스키마, DB와 상호작용하는 코드를 설명한다 | P1 s4 |
| R-07 | 보고서 분량은 **6페이지**다 | P1 s4 |

## 2. 보고서 구조 (MUST)

| ID | 섹션 | 반드시 들어갈 내용 | 근거 |
|---|---|---|---|
| R-10 | Abstract | 작업 전체를 5–6문장으로 요약 | P1 s5 |
| R-11 | Introduction | ① 주제의 중요성 ② 일반적인 문제 정의 ③ 기존 연구/서비스와 비교 ④ 제안 기법 ⑤ 평가 요약 ⑥ 이후 장 구성 | P1 s5–7 |
| R-12 | Contribution | **3개 이상**. 예: Analysis / Design and Implementation / Evaluation and Performance | P1 s7 |
| R-13 | Background and Motivation | 대상 시스템이 무엇인지(예: "PoS란?"), 왜 이 문제를 다루는지 | P1 s4, s14; P4 s5 |
| R-14 | Design: Overall architecture | 기법의 목표와 설계 방향 | P1 s8 |
| R-15 | Design: 상세 설계 | 전체 절차와 하위 절. 데이터 구조, **E-R 모델** 포함 | P1 s9, s14 |
| R-16 | Implementation | 실제 함수/코드를 근거로 설명한다. **읽은 사람이 재현할 수 있어야** 한다 | P1 s10 |
| R-17 | 단점, 안정성, 견고성 | 기법의 단점과 오버헤드, 그 오버헤드가 시스템에 주는 영향이 작은 이유 | P1 s11 |
| R-18 | Evaluation: 개선 이유 | 성능이 왜 개선되는지 | P1 s12 |
| R-19 | Evaluation: 실험 분석 | **함수 단위 프로파일링 시간이나 호출 횟수** 같은 정량 근거 | P1 s12 |
| R-20 | Evaluation: 비교 | 기존 방식(baseline/state of the art)과 비교한 표나 그래프 | P1 s13 |
| R-21 | Evaluation: 실행 결과 | **쿼리 실행 결과**(콘솔 출력이나 화면 캡처) | P1 s14; P4 s9–10 |
| R-22 | Conclusion | 결론 | P1 s4 |

## 3. 예시 보고서와 General Advice 기반 (SHOULD)

| ID | 요구사항 | 근거 |
|---|---|---|
| R-30 | **실제 문제**를 주제로 고른다. 일반적인 주제도 허용되지만 실제 이슈가 학습량과 쓸거리가 많다 | P4 s23 |
| R-31 | ER 다이어그램과 스키마 표: PK, FK, NOT NULL, AUTO_INCREMENT, 타입을 표기한다 | P4 s7, s13–14, s20 |
| R-32 | 기능 단위 메뉴 구조를 둔다. 사용자 역할별로 메뉴를 분리한다(예: 고객 / 관리자) | P4 s15 (항공 예시: customer menu / airline menu) |
| R-33 | 기능마다 **코드 + 설명 + 실행 결과**를 세트로 제시한다 | P4 s9–10 |
| R-34 | DB 연결 코드를 별도 절로 설명한다 | P4 s8 |
| R-35 | 장점, 한계, 문제점(Findings, "What can you do better?")을 정리한다 | P4 s10, s22, s23 |
| R-36 | 수업에서 다룬 SQL을 쓴다: `CREATE DATABASE/TABLE`, `INSERT`, `ALL`/`SOME` 집합 비교 서브쿼리 | P3 |
| R-37 | 쿼리 개선 사례를 남긴다: 뷰(`CREATE VIEW`), 집계(`GROUP_CONCAT` 등)로 화면/검색 문제를 해결한 과정 | P4 s22 |

## 4. 품질 기준 [추론]

자료에 명시되지 않았다. 예시 보고서의 한계("등록번호만으로 삭제하면 다른 학생의 신청도 지워진다", P4 s10)를 피하고 Evaluation 섹션을 정량적으로 채우려고 채택한 기준이다.

| ID | 기준 |
|---|---|
| R-40 | 테이블 5개 이상이고, 1:N과 N:M 관계가 각각 1개 이상 있다. 3NF 수준으로 정규화한다 |
| R-41 | CRUD가 모두 있고, 사용자 입력은 **PreparedStatement / 파라미터 바인딩**으로만 SQL에 넣는다. 문자열 연결로 쿼리를 만들지 않는다(SQL injection 방지). 예시 코드도 `prepareStatement`를 쓴다 |
| R-42 | 소유권과 권한 검사: 수정·삭제할 때 행의 소유자를 조건으로 건다(P4 s10 한계 재발 방지) |
| R-43 | 여러 테이블을 바꾸는 작업은 **트랜잭션**으로 묶고, 실패하면 롤백한다 |
| R-44 | 무결성 제약(PK, FK, UNIQUE, CHECK, NOT NULL)으로 잘못된 데이터를 DB 수준에서 막는다 |
| R-45 | JOIN, GROUP BY/HAVING, 서브쿼리, VIEW를 각각 1회 이상 의미 있게 쓴다 |
| R-46 | **측정 가능한 개선 기법**이 1개 이상 있다. 예: 인덱스, 쿼리 재작성, 배치 트랜잭션, 키셋 페이지네이션, FTS. baseline과 비교한 수치로 R-18~R-20을 채운다 |
| R-47 | 재현성: `schema.sql`, `seed.sql`(또는 데이터 생성 스크립트), 실행 방법을 담은 README, 벤치마크 스크립트가 저장소에 있고, 명령 1–2개로 재현된다 |
| R-48 | 잘못된 입력(형식 오류, 없는 ID, 제약 위반)이 들어와도 프로그램이 죽지 않고 메시지를 출력한다 |
| R-49 | 평가용 데이터는 성능 차이가 보일 만큼 크게 만든다(최소 수만~수십만 행). 실험 환경(CPU, OS, DB 버전)을 기록한다 |

## 5. 범위 밖

- Quiz(P1 s2): 별도 과제다. DB 설치, SQL 검증, 2페이지 해설. 텀프로젝트 결과물에는 포함하지 않는다.
- DB 소스 빌드(P1 s17–25): 설치 방법은 자유다. apt, Windows 인스톨러, SQLite 단일 파일 모두 가능하다.

## 6. 최종 검증 체크리스트 (fable5.2)

fable5.2는 아래 항목을 **증거물로** 확인한다. 증거가 없는 항목은 불합격으로 처리한다.

| 영역 | 확인 ID | 증거물 / 확인 방법 |
|---|---|---|
| 실행 | R-01~05, R-47, R-48 | 클린 환경에서 README 절차대로 스키마 생성 → 시드 → 실행. 메뉴 전체를 한 번씩 돌린 로그 |
| 스키마 | R-31, R-40, R-44 | `schema.sql`과 ERD가 일치하는지. 제약 위반 INSERT가 거부되는지 |
| 보안·정합성 | R-41~43 | 코드에서 문자열 연결로 만든 SQL을 grep으로 찾는다. 타인 소유 행 삭제 시도. 트랜잭션 도중 실패를 주입해 롤백되는지 |
| SQL 활용 | R-36, R-37, R-45 | 쿼리 목록에 JOIN, GROUP BY, 서브쿼리(ALL/SOME), VIEW가 실제로 쓰였는지 |
| 평가 | R-18~21, R-46, R-49 | 벤치마크 스크립트를 재실행해 보고서 수치와 ±오차 범위 안에서 일치하는지. `EXPLAIN` / `EXPLAIN QUERY PLAN` 출력 첨부 여부 |
| 보고서 | R-06, R-07, R-10~17, R-22, R-35 | 섹션 존재 여부, 6페이지, Introduction 6요소, Contribution 3개 이상, 코드 인용이 실제 코드와 일치하는지 |
