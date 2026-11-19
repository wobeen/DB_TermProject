-- =====================================================================
-- 뷰. 스냅샷 기준(as_of) 뷰는 snapshot과 조인해 as_of_date '미만' 데이터만 노출한다.
-- 백테스트/추천 코드는 원천 테이블 대신 반드시 *_asof 뷰나 snapshot_id 키 테이블을 쓴다.
-- =====================================================================

-- 시즌 종료일(season+1년 6/30)이 as_of 이전인 완료 시즌만
CREATE VIEW v_player_season_asof AS
SELECT s.snapshot_id, ps.*
FROM snapshot s
JOIN player_season ps ON date((ps.season + 1) || '-06-30') < s.as_of_date;

CREATE VIEW v_valuation_asof AS
SELECT s.snapshot_id, v.player_id, v.date, v.market_value_eur, v.club_id
FROM snapshot s
JOIN player_valuation v ON v.date < s.as_of_date;

-- as_of 직전 최신 시장가치 (PK (player_id, date) 인덱스로 상관 서브쿼리 처리)
CREATE VIEW v_latest_value_asof AS
SELECT s.snapshot_id, v.player_id, v.date AS value_date, v.market_value_eur
FROM snapshot s
JOIN player_valuation v
  ON v.date = (SELECT MAX(v2.date) FROM player_valuation v2
               WHERE v2.player_id = v.player_id AND v2.date < s.as_of_date);

CREATE VIEW v_player_age_asof AS
SELECT s.snapshot_id, p.player_id,
       CAST((julianday(s.as_of_date) - julianday(p.date_of_birth)) / 365.25 AS INTEGER) AS age
FROM snapshot s
JOIN player p ON p.date_of_birth IS NOT NULL AND p.date_of_birth < s.as_of_date;

-- 현재 시점 선수 카드 (서비스 검색/프로필 헤더용)
CREATE VIEW v_player_card AS
SELECT p.player_id, p.name, p.date_of_birth, p.position, p.sub_position, p.pos_group,
       p.foot, p.height_cm, p.country_of_citizenship,
       c.club_id AS current_club_id, c.name AS current_club_name,
       (SELECT v.market_value_eur FROM player_valuation v
         WHERE v.player_id = p.player_id ORDER BY v.date DESC LIMIT 1) AS latest_value_eur,
       (SELECT MAX(v.market_value_eur) FROM player_valuation v
         WHERE v.player_id = p.player_id) AS peak_value_eur
FROM player p
LEFT JOIN club c ON c.club_id = p.current_club_id;

-- 사용자별 활동 요약 (관리자 메뉴)
CREATE VIEW v_user_activity AS
SELECT u.user_id, u.username, u.role,
       (SELECT COUNT(*) FROM watchlist w WHERE w.user_id = u.user_id)          AS watchlist_count,
       (SELECT COUNT(*) FROM scouting_note n WHERE n.user_id = u.user_id)      AS note_count,
       (SELECT COUNT(*) FROM recommendation_run r WHERE r.user_id = u.user_id) AS run_count
FROM app_user u;

-- 추천 결과 + 사후 결과(outcome 스냅샷 라벨) 비교용
CREATE VIEW v_recommendation_detail AS
SELECT r.run_id, r.method, r.pos_group, r.snapshot_id, r.def_id,
       i.rank, i.player_id, p.name, i.season, i.score, i.wc_neighbors
FROM recommendation_run r
JOIN recommendation_item i ON i.run_id = r.run_id
JOIN player p ON p.player_id = i.player_id;
