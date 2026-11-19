-- =====================================================================
-- 성능용 보조 인덱스. PK/UNIQUE가 만드는 인덱스는 schema.sql에 있다.
-- 벤치마크 구성 B1은 이 파일을 적용하지 않은 DB, B2/P는 적용한 DB를 쓴다.
-- 모든 인덱스 이름은 ix_ 접두사 (B1 생성 시 일괄 DROP 대상).
-- =====================================================================

-- 원천 계층: 원천 집계 경로(B2)와 파생 빌드용
CREATE INDEX ix_appearance_player_date   ON appearance(player_id, date);
CREATE INDEX ix_appearance_comp_date     ON appearance(competition_id, date);
CREATE INDEX ix_game_comp_season         ON game(competition_id, season);
CREATE INDEX ix_game_event_game_type     ON game_event(game_id, type, minute);
CREATE INDEX ix_game_event_player_in     ON game_event(player_in_id, game_id) WHERE type = 'Substitutions';
CREATE INDEX ix_transfer_player_date     ON transfer(player_id, transfer_date);
CREATE INDEX ix_player_posgroup_dob      ON player(pos_group, date_of_birth);
CREATE INDEX ix_player_name              ON player(name COLLATE NOCASE);

-- 파생 계층: 후보 선정, 코호트 k-NN
CREATE INDEX ix_player_season_cohort     ON player_season(season, pos_group, age);
CREATE INDEX ix_psm_metric_season        ON player_season_metric(metric_code, season);
CREATE INDEX ix_psz_cohort               ON player_season_z(snapshot_id, pos_group, age, metric_code, player_id, season, z);
CREATE INDEX ix_wcl_snapshot_def_flag    ON world_class_label(snapshot_id, def_id, is_world_class);

-- 서비스 계층
CREATE INDEX ix_note_player              ON scouting_note(player_id);
CREATE INDEX ix_note_user                ON scouting_note(user_id, updated_at);
CREATE INDEX ix_run_user_created         ON recommendation_run(user_id, created_at);
