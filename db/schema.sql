-- =====================================================================
-- Football Scouting DB  (SQLite >= 3.37, STRICT tables)
-- 계약: docs/CONTRACT.md. 이 파일의 변경은 coordinator만 한다.
-- 연결마다 PRAGMA foreign_keys = ON 필수 (scouting.db.connect가 보장).
-- 날짜는 전부 ISO-8601 TEXT('YYYY-MM-DD'), CHECK로 형식 강제.
-- 성능용 보조 인덱스는 db/indexes.sql (벤치마크에서 on/off 비교 대상).
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- 1. 원천(Core) 계층: Transfermarkt 데이터셋을 정규화해 적재
-- ---------------------------------------------------------------------

CREATE TABLE competition (
    competition_id   TEXT    PRIMARY KEY,
    name             TEXT    NOT NULL,
    type             TEXT    NOT NULL CHECK (type IN ('domestic_league','domestic_cup',
                                 'international_cup','national_team_competition','other')),
    sub_type         TEXT,
    country_name     TEXT,
    confederation    TEXT,
    -- 2012~2025 시즌 출전 기록이 일관되게 수집된 1부 리그(14개)만 1
    is_covered       INTEGER NOT NULL DEFAULT 0 CHECK (is_covered IN (0,1)),
    is_big5          INTEGER NOT NULL DEFAULT 0 CHECK (is_big5 IN (0,1)),
    is_uefa_club     INTEGER NOT NULL DEFAULT 0 CHECK (is_uefa_club IN (0,1)),  -- CL, EL
    CHECK (is_big5 = 0 OR is_covered = 1)
) STRICT;

CREATE TABLE club (
    club_id                  INTEGER PRIMARY KEY,
    name                     TEXT    NOT NULL,
    domestic_competition_id  TEXT    REFERENCES competition(competition_id),
    -- clubs.csv에 없고 경기/출전/이적에만 등장하는 구단은 stub(1)으로 생성
    is_stub                  INTEGER NOT NULL DEFAULT 0 CHECK (is_stub IN (0,1))
) STRICT;

CREATE TABLE player (
    player_id               INTEGER PRIMARY KEY,
    name                    TEXT    NOT NULL,
    date_of_birth           TEXT    CHECK (date_of_birth IS date(date_of_birth)),
    position                TEXT    NOT NULL CHECK (position IN ('Goalkeeper','Defender','Midfield','Attack','Missing')),
    sub_position            TEXT,
    pos_group               TEXT    GENERATED ALWAYS AS (
                                CASE position WHEN 'Goalkeeper' THEN 'GK' WHEN 'Defender' THEN 'DF'
                                              WHEN 'Midfield'   THEN 'MF' WHEN 'Attack'   THEN 'FW' END) STORED,
    foot                    TEXT    CHECK (foot IS NULL OR foot IN ('left','right','both')),
    height_cm               INTEGER CHECK (height_cm IS NULL OR height_cm BETWEEN 140 AND 220),
    country_of_citizenship  TEXT,
    current_club_id         INTEGER REFERENCES club(club_id)
) STRICT;

CREATE TABLE game (
    game_id         INTEGER PRIMARY KEY,
    competition_id  TEXT    NOT NULL REFERENCES competition(competition_id),
    season          INTEGER NOT NULL CHECK (season BETWEEN 1990 AND 2100),  -- 2018 = 2018/19 시즌
    round           TEXT,
    date            TEXT    NOT NULL CHECK (date IS date(date)),
    home_club_id    INTEGER NOT NULL REFERENCES club(club_id),
    away_club_id    INTEGER NOT NULL REFERENCES club(club_id),
    home_goals      INTEGER NOT NULL CHECK (home_goals >= 0),
    away_goals      INTEGER NOT NULL CHECK (away_goals >= 0),
    CHECK (home_club_id <> away_club_id)
) STRICT;

CREATE TABLE appearance (
    appearance_id   TEXT    PRIMARY KEY,                 -- '<game_id>_<player_id>'
    game_id         INTEGER NOT NULL REFERENCES game(game_id),
    player_id       INTEGER NOT NULL REFERENCES player(player_id),
    club_id         INTEGER NOT NULL REFERENCES club(club_id),
    date            TEXT    NOT NULL CHECK (date IS date(date)),
    competition_id  TEXT    NOT NULL REFERENCES competition(competition_id),
    minutes_played  INTEGER NOT NULL CHECK (minutes_played BETWEEN 0 AND 150),
    goals           INTEGER NOT NULL DEFAULT 0 CHECK (goals >= 0),
    assists         INTEGER NOT NULL DEFAULT 0 CHECK (assists >= 0),
    yellow_cards    INTEGER NOT NULL DEFAULT 0 CHECK (yellow_cards BETWEEN 0 AND 2),
    red_cards       INTEGER NOT NULL DEFAULT 0 CHECK (red_cards BETWEEN 0 AND 1),
    UNIQUE (game_id, player_id)
) STRICT;

CREATE TABLE game_lineup (
    game_id       INTEGER NOT NULL REFERENCES game(game_id),
    player_id     INTEGER NOT NULL REFERENCES player(player_id),
    club_id       INTEGER NOT NULL REFERENCES club(club_id),
    is_starter    INTEGER NOT NULL CHECK (is_starter IN (0,1)),
    position      TEXT,                                  -- 해당 경기 실제 포지션 (예: 'Centre-Back')
    team_captain  INTEGER NOT NULL DEFAULT 0 CHECK (team_captain IN (0,1)),
    PRIMARY KEY (game_id, player_id)
) WITHOUT ROWID, STRICT;

-- player_id / player_in_id / player_assist_id에는 FK를 걸지 않는다:
-- players.csv에 없는 선수의 득점 이벤트도 구단 득점 집계(club_id)에 필요하므로 버리면 안 된다.
CREATE TABLE game_event (
    game_event_id     TEXT    PRIMARY KEY,
    game_id           INTEGER NOT NULL REFERENCES game(game_id),
    minute            INTEGER NOT NULL CHECK (minute BETWEEN -1 AND 130),   -- -1 = 분 정보 없음
    type              TEXT    NOT NULL CHECK (type IN ('Goals','Cards','Substitutions','Shootout')),
    club_id           INTEGER NOT NULL REFERENCES club(club_id),  -- Goals: 득점이 인정된 구단(자책골 포함)
    player_id         INTEGER,          -- Substitutions: 교체 아웃 선수
    player_in_id      INTEGER,          -- Substitutions: 교체 인 선수
    player_assist_id  INTEGER,
    is_sending_off    INTEGER NOT NULL DEFAULT 0 CHECK (is_sending_off IN (0,1)),  -- 'Red card%' 또는 'Second yellow%'
    description       TEXT,
    CHECK (is_sending_off = 0 OR type = 'Cards')
) STRICT;

CREATE TABLE player_valuation (
    player_id         INTEGER NOT NULL REFERENCES player(player_id),
    date              TEXT    NOT NULL CHECK (date IS date(date)),
    market_value_eur  INTEGER NOT NULL CHECK (market_value_eur >= 0),
    club_id           INTEGER REFERENCES club(club_id),
    PRIMARY KEY (player_id, date)
) WITHOUT ROWID, STRICT;

CREATE TABLE transfer (
    transfer_id       INTEGER PRIMARY KEY,
    player_id         INTEGER NOT NULL REFERENCES player(player_id),
    transfer_date     TEXT    NOT NULL CHECK (transfer_date IS date(transfer_date)),
    transfer_season   TEXT,
    from_club_id      INTEGER REFERENCES club(club_id),
    to_club_id        INTEGER REFERENCES club(club_id),
    fee_eur           REAL    CHECK (fee_eur IS NULL OR fee_eur >= 0),
    market_value_eur  REAL    CHECK (market_value_eur IS NULL OR market_value_eur >= 0)
) STRICT;

-- ---------------------------------------------------------------------
-- 2. 파생(Derived) 계층: 시즌 사실 → 지표 → 스냅샷별 표준화
--    player_season / player_season_metric 은 시즌 단위 사실이라 스냅샷과 무관하다.
--    스냅샷 의존 데이터(코호트 기준치, z-score, 라벨)는 snapshot_id로 분리해
--    미래 정보 누수를 스키마 수준에서 차단한다.
-- ---------------------------------------------------------------------

CREATE TABLE competition_season_strength (
    competition_id       TEXT    NOT NULL REFERENCES competition(competition_id),
    season               INTEGER NOT NULL,
    avg_player_value_eur REAL    NOT NULL CHECK (avg_player_value_eur >= 0),  -- 시즌 시작(7/1) 이전 최신 시장가치 평균
    n_players            INTEGER NOT NULL CHECK (n_players > 0),
    PRIMARY KEY (competition_id, season)
) WITHOUT ROWID, STRICT;

CREATE TABLE player_season (
    player_id          INTEGER NOT NULL REFERENCES player(player_id),
    season             INTEGER NOT NULL,
    age                INTEGER NOT NULL CHECK (age BETWEEN 14 AND 45),   -- 시즌 시작일(season-07-01) 기준 만 나이
    pos_group          TEXT    NOT NULL CHECK (pos_group IN ('GK','DF','MF','FW')),
    main_club_id       INTEGER NOT NULL REFERENCES club(club_id),       -- 리그 출전 시간이 가장 많은 구단
    league_apps        INTEGER NOT NULL CHECK (league_apps >= 0),
    league_starts      INTEGER NOT NULL CHECK (league_starts BETWEEN 0 AND league_apps),
    league_minutes     INTEGER NOT NULL CHECK (league_minutes >= 0),
    team_league_games  INTEGER NOT NULL CHECK (team_league_games > 0),  -- 소속 구단(들)의 해당 시즌 리그 경기 수
    goals              INTEGER NOT NULL CHECK (goals >= 0),
    assists            INTEGER NOT NULL CHECK (assists >= 0),
    yellow_cards       INTEGER NOT NULL CHECK (yellow_cards >= 0),
    red_cards          INTEGER NOT NULL CHECK (red_cards >= 0),
    onpitch_gf         INTEGER NOT NULL CHECK (onpitch_gf >= 0),       -- 출전 중 팀 득점
    onpitch_ga         INTEGER NOT NULL CHECK (onpitch_ga >= 0),       -- 출전 중 팀 실점
    clean_sheets       INTEGER NOT NULL CHECK (clean_sheets BETWEEN 0 AND league_starts),
    uefa_minutes       INTEGER NOT NULL DEFAULT 0 CHECK (uefa_minutes >= 0),
    comp_strength_eur  REAL    NOT NULL CHECK (comp_strength_eur >= 0), -- 출전 시간 가중 리그 수준
    PRIMARY KEY (player_id, season)
) WITHOUT ROWID, STRICT;

CREATE TABLE metric (
    metric_code       TEXT    PRIMARY KEY,
    name_ko           TEXT    NOT NULL,
    description       TEXT    NOT NULL,
    higher_is_better  INTEGER NOT NULL CHECK (higher_is_better IN (0,1)),
    min_minutes       INTEGER NOT NULL DEFAULT 0 CHECK (min_minutes >= 0)  -- 이 출전 시간 미만이면 값 미산출
) STRICT;

CREATE TABLE metric_weight (
    pos_group    TEXT NOT NULL CHECK (pos_group IN ('GK','DF','MF','FW')),
    metric_code  TEXT NOT NULL REFERENCES metric(metric_code),
    weight       REAL NOT NULL CHECK (weight > 0),
    PRIMARY KEY (pos_group, metric_code)
) WITHOUT ROWID, STRICT;

CREATE TABLE player_season_metric (
    player_id    INTEGER NOT NULL,
    season       INTEGER NOT NULL,
    metric_code  TEXT    NOT NULL REFERENCES metric(metric_code),
    value        REAL    NOT NULL,
    PRIMARY KEY (player_id, season, metric_code),
    FOREIGN KEY (player_id, season) REFERENCES player_season(player_id, season) ON DELETE CASCADE
) WITHOUT ROWID, STRICT;

CREATE TABLE snapshot (
    snapshot_id  INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL UNIQUE,
    as_of_date   TEXT    NOT NULL CHECK (as_of_date IS date(as_of_date)),  -- 이 날짜 '미만' 데이터만 보인다
    built_at     TEXT,                                                    -- 파생 계산 완료 시각(NULL = 미완료)
    CHECK (built_at IS datetime(built_at))
) STRICT;

CREATE TABLE cohort_baseline (
    snapshot_id  INTEGER NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    pos_group    TEXT    NOT NULL CHECK (pos_group IN ('GK','DF','MF','FW')),
    age          INTEGER NOT NULL,
    metric_code  TEXT    NOT NULL REFERENCES metric(metric_code),
    mean         REAL    NOT NULL,
    std          REAL    NOT NULL CHECK (std >= 0),
    n            INTEGER NOT NULL CHECK (n > 0),
    PRIMARY KEY (snapshot_id, pos_group, age, metric_code)
) WITHOUT ROWID, STRICT;

-- age, pos_group은 player_season과 중복이지만 k-NN 인덱스((snapshot_id,pos_group,age,metric_code))를 위해
-- 의도적으로 비정규화했다. 일관성은 파생 빌드가 같은 트랜잭션에서 함께 쓰는 것으로 보장한다.
CREATE TABLE player_season_z (
    snapshot_id  INTEGER NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    player_id    INTEGER NOT NULL,
    season       INTEGER NOT NULL,
    pos_group    TEXT    NOT NULL CHECK (pos_group IN ('GK','DF','MF','FW')),
    age          INTEGER NOT NULL,
    metric_code  TEXT    NOT NULL REFERENCES metric(metric_code),
    z            REAL    NOT NULL,   -- higher_is_better=0 지표는 부호를 뒤집어 저장(클수록 좋음)
    PRIMARY KEY (snapshot_id, player_id, season, metric_code),
    FOREIGN KEY (player_id, season) REFERENCES player_season(player_id, season) ON DELETE CASCADE
) WITHOUT ROWID, STRICT;

CREATE TABLE world_class_definition (
    def_id                    INTEGER PRIMARY KEY,
    code                      TEXT    NOT NULL UNIQUE,
    name_ko                   TEXT    NOT NULL,
    rule_type                 TEXT    NOT NULL CHECK (rule_type IN ('peak_value','big5_regular')),
    -- peak_value: as_of 이전 최고 시장가치 >= 임계값(포지션별)
    value_threshold_eur       INTEGER CHECK (value_threshold_eur IS NULL OR value_threshold_eur > 0),
    gk_value_threshold_eur    INTEGER CHECK (gk_value_threshold_eur IS NULL OR gk_value_threshold_eur > 0),
    -- big5_regular: big5 리그에서 league_minutes >= min_league_minutes 인 시즌 수 >= min_seasons
    --               그리고 CL 출전 시간 합 >= min_cl_minutes
    min_seasons               INTEGER CHECK (min_seasons IS NULL OR min_seasons > 0),
    min_league_minutes        INTEGER CHECK (min_league_minutes IS NULL OR min_league_minutes > 0),
    min_cl_minutes            INTEGER CHECK (min_cl_minutes IS NULL OR min_cl_minutes >= 0),
    CHECK (
        (rule_type = 'peak_value'   AND value_threshold_eur IS NOT NULL AND gk_value_threshold_eur IS NOT NULL
                                    AND min_seasons IS NULL AND min_league_minutes IS NULL AND min_cl_minutes IS NULL)
     OR (rule_type = 'big5_regular' AND min_seasons IS NOT NULL AND min_league_minutes IS NOT NULL AND min_cl_minutes IS NOT NULL
                                    AND value_threshold_eur IS NULL AND gk_value_threshold_eur IS NULL)
    )
) STRICT;

CREATE TABLE world_class_label (
    snapshot_id     INTEGER NOT NULL REFERENCES snapshot(snapshot_id) ON DELETE CASCADE,
    def_id          INTEGER NOT NULL REFERENCES world_class_definition(def_id) ON DELETE CASCADE,
    player_id       INTEGER NOT NULL REFERENCES player(player_id),
    is_world_class  INTEGER NOT NULL CHECK (is_world_class IN (0,1)),
    achieved_on     TEXT    CHECK (achieved_on IS date(achieved_on)),
    CHECK ((is_world_class = 1) = (achieved_on IS NOT NULL)),
    PRIMARY KEY (snapshot_id, def_id, player_id)
) WITHOUT ROWID, STRICT;

-- ---------------------------------------------------------------------
-- 3. 서비스 계층: 사용자, 워치리스트, 노트, 추천 실행 기록
-- ---------------------------------------------------------------------

CREATE TABLE app_user (
    user_id        INTEGER PRIMARY KEY,
    username       TEXT    NOT NULL UNIQUE CHECK (length(username) BETWEEN 3 AND 32),
    password_hash  TEXT    NOT NULL,          -- 'pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>'
    role           TEXT    NOT NULL DEFAULT 'scout' CHECK (role IN ('scout','admin')),
    created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE TABLE watchlist (
    user_id    INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    player_id  INTEGER NOT NULL REFERENCES player(player_id),
    added_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    memo       TEXT    CHECK (memo IS NULL OR length(memo) <= 200),
    PRIMARY KEY (user_id, player_id)
) WITHOUT ROWID, STRICT;

CREATE TABLE scouting_note (
    note_id     INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    player_id   INTEGER NOT NULL REFERENCES player(player_id),
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    body        TEXT    NOT NULL CHECK (length(trim(body)) BETWEEN 1 AND 2000),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (updated_at >= created_at)
) STRICT;

CREATE TABLE recommendation_run (
    run_id            INTEGER PRIMARY KEY,
    user_id           INTEGER REFERENCES app_user(user_id) ON DELETE SET NULL,  -- NULL = 배치/벤치 실행
    snapshot_id       INTEGER NOT NULL REFERENCES snapshot(snapshot_id),
    def_id            INTEGER NOT NULL REFERENCES world_class_definition(def_id),
    method            TEXT    NOT NULL CHECK (method IN ('random','market_value','similarity','hybrid')),
    pos_group         TEXT    NOT NULL CHECK (pos_group IN ('GK','DF','MF','FW')),
    max_age           INTEGER NOT NULL CHECK (max_age BETWEEN 15 AND 30),
    min_minutes       INTEGER NOT NULL CHECK (min_minutes >= 0),
    k                 INTEGER NOT NULL CHECK (k > 0),
    pool_lag_seasons  INTEGER NOT NULL CHECK (pool_lag_seasons >= 0),
    top_n             INTEGER NOT NULL CHECK (top_n > 0),
    seed              INTEGER,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE TABLE recommendation_item (
    run_id         INTEGER NOT NULL REFERENCES recommendation_run(run_id) ON DELETE CASCADE,
    rank           INTEGER NOT NULL CHECK (rank > 0),
    player_id      INTEGER NOT NULL REFERENCES player(player_id),
    season         INTEGER NOT NULL,          -- 추천 근거가 된 시즌(as_of 직전 완료 시즌)
    score          REAL    NOT NULL,
    wc_neighbors   INTEGER CHECK (wc_neighbors IS NULL OR wc_neighbors >= 0),  -- similarity/hybrid만
    PRIMARY KEY (run_id, rank),
    UNIQUE (run_id, player_id)
) STRICT;

CREATE TABLE recommendation_evidence (
    run_id              INTEGER NOT NULL,
    player_id           INTEGER NOT NULL,
    neighbor_player_id  INTEGER NOT NULL REFERENCES player(player_id),
    neighbor_season     INTEGER NOT NULL,
    distance            REAL    NOT NULL CHECK (distance >= 0),
    neighbor_is_wc      INTEGER NOT NULL CHECK (neighbor_is_wc IN (0,1)),
    PRIMARY KEY (run_id, player_id, neighbor_player_id, neighbor_season),
    FOREIGN KEY (run_id, player_id) REFERENCES recommendation_item(run_id, player_id) ON DELETE CASCADE
) WITHOUT ROWID, STRICT;

CREATE TABLE backtest_result (
    run_id               INTEGER NOT NULL REFERENCES recommendation_run(run_id) ON DELETE CASCADE,
    outcome_snapshot_id  INTEGER NOT NULL REFERENCES snapshot(snapshot_id),
    k_eval               INTEGER NOT NULL CHECK (k_eval > 0),
    n_candidates         INTEGER NOT NULL CHECK (n_candidates >= 0),
    n_positive           INTEGER NOT NULL CHECK (n_positive BETWEEN 0 AND n_candidates),
    hits                 INTEGER NOT NULL CHECK (hits BETWEEN 0 AND k_eval),
    precision_at_k       REAL    NOT NULL CHECK (precision_at_k BETWEEN 0 AND 1),
    recall_at_k          REAL    CHECK (recall_at_k IS NULL OR recall_at_k BETWEEN 0 AND 1),
    evaluated_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (run_id, outcome_snapshot_id, k_eval)
) WITHOUT ROWID, STRICT;

-- note 수정 시 updated_at 자동 갱신
CREATE TRIGGER trg_scouting_note_touch
AFTER UPDATE OF rating, body ON scouting_note
FOR EACH ROW WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE scouting_note SET updated_at = datetime('now') WHERE note_id = NEW.note_id;
END;
