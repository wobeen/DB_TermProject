-- =====================================================================
-- 기준 데이터: 지표 사전, 포지션별 가중치, 월드클래스 정의.
-- 원천 적재와 무관하게 schema.sql 직후 적용한다.
-- 공식은 docs/CONTRACT.md §4 와 일치해야 한다.
-- =====================================================================

INSERT INTO metric (metric_code, name_ko, description, higher_is_better, min_minutes) VALUES
 ('minutes_share',    '출전 시간 점유율',   'league_minutes / (team_league_games*90), 1로 상한',                 1,   0),
 ('start_rate',       '선발 비율',          'league_starts / team_league_games, 1로 상한',                       1,   0),
 ('goals_per90',      '90분당 득점',        'goals*90/league_minutes',                                           1, 450),
 ('assists_per90',    '90분당 도움',        'assists*90/league_minutes',                                         1, 450),
 ('ga_per90',         '90분당 공격포인트',  '(goals+assists)*90/league_minutes',                                 1, 450),
 ('onpitch_gd_per90', '출전 중 90분당 득실차', '(onpitch_gf-onpitch_ga)*90/league_minutes',                      1, 450),
 ('onpitch_ga_per90', '출전 중 90분당 실점', 'onpitch_ga*90/league_minutes',                                     0, 450),
 ('clean_sheet_rate', '무실점 선발 비율',   'clean_sheets/league_starts (league_starts>0일 때만)',               1, 450),
 ('cards_per90',      '90분당 카드',        '(yellow_cards+3*red_cards)*90/league_minutes',                      0, 450),
 ('comp_strength',    '리그 수준',          'log10(comp_strength_eur + 1)',                                      1,   0),
 ('uefa_minutes',     'UEFA 대회 출전',     'ln(1 + uefa_minutes)',                                              1,   0);

INSERT INTO metric_weight (pos_group, metric_code, weight) VALUES
 ('GK','minutes_share',2.0), ('GK','start_rate',1.0), ('GK','onpitch_ga_per90',2.0), ('GK','clean_sheet_rate',2.0),
 ('GK','comp_strength',2.0), ('GK','uefa_minutes',1.0),
 ('DF','minutes_share',2.0), ('DF','start_rate',1.0), ('DF','onpitch_ga_per90',1.5), ('DF','clean_sheet_rate',1.0),
 ('DF','onpitch_gd_per90',1.0), ('DF','ga_per90',0.5), ('DF','cards_per90',0.5), ('DF','comp_strength',2.0),
 ('DF','uefa_minutes',1.0),
 ('MF','minutes_share',2.0), ('MF','start_rate',1.0), ('MF','ga_per90',1.5), ('MF','assists_per90',1.0),
 ('MF','onpitch_gd_per90',1.0), ('MF','comp_strength',2.0), ('MF','uefa_minutes',1.0),
 ('FW','minutes_share',2.0), ('FW','start_rate',1.0), ('FW','goals_per90',2.0), ('FW','ga_per90',1.5),
 ('FW','onpitch_gd_per90',0.5), ('FW','comp_strength',2.0), ('FW','uefa_minutes',1.0);

INSERT INTO world_class_definition
 (def_id, code, name_ko, rule_type, value_threshold_eur, gk_value_threshold_eur, min_seasons, min_league_minutes, min_cl_minutes)
VALUES
 (1, 'peak_value_50m', '최고 시장가치 €50M 이상 (GK €30M)', 'peak_value',   50000000, 30000000, NULL, NULL, NULL),
 (2, 'big5_cl_regular', '빅5 리그 주전 3시즌 + CL 900분',  'big5_regular', NULL,     NULL,     3,    2000, 900);
