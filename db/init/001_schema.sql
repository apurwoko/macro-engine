-- Skema MySQL 8.x. Dijalankan otomatis saat volume MySQL pertama kali dibuat.
-- Semua waktu disimpan UTC.

SET NAMES utf8mb4;
SET time_zone = '+00:00';

-- ---------------------------------------------------------------- data mentah

-- Seri makro dari FRED (id apa adanya) dan EIA (id diawali "EIA_").
CREATE TABLE IF NOT EXISTS macro_observations (
  series_id  VARCHAR(40) NOT NULL,
  obs_date   DATE        NOT NULL,
  value      DOUBLE      NOT NULL,
  fetched_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (series_id, obs_date)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS prices_daily (
  symbol     VARCHAR(24) NOT NULL,
  trade_date DATE        NOT NULL,
  open       DOUBLE NULL,
  high       DOUBLE NULL,
  low        DOUBLE NULL,
  close      DOUBLE NOT NULL,
  volume     DOUBLE NULL,
  PRIMARY KEY (symbol, trade_date)
) ENGINE=InnoDB;

-- Posisi CFTC (Commitments of Traders), satu baris per pasar per tanggal laporan (Selasa).
CREATE TABLE IF NOT EXISTS cot_positions (
  market_key    VARCHAR(24) NOT NULL,
  report_date   DATE        NOT NULL,
  report_type   VARCHAR(12) NOT NULL,
  contract_code VARCHAR(12) NOT NULL,
  long_pos      BIGINT NULL,
  short_pos     BIGINT NULL,
  net_pos       BIGINT NOT NULL,
  open_interest BIGINT NULL,
  PRIMARY KEY (market_key, report_date)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS calendar_events (
  id         BIGINT NOT NULL AUTO_INCREMENT,
  event_time DATETIME     NOT NULL,
  country    VARCHAR(8)   NOT NULL DEFAULT '',
  currency   VARCHAR(3)   NOT NULL,
  title      VARCHAR(160) NOT NULL,
  impact     ENUM('low','medium','high') NOT NULL DEFAULT 'medium',
  forecast   VARCHAR(32) NULL,
  previous   VARCHAR(32) NULL,
  actual     VARCHAR(32) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_event (event_time, country, title),
  KEY idx_time (event_time)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------- berita + LLM

CREATE TABLE IF NOT EXISTS headlines (
  id             BIGINT NOT NULL AUTO_INCREMENT,
  url_hash       CHAR(40)     NOT NULL,
  published_at   DATETIME     NOT NULL,
  source         VARCHAR(64)  NOT NULL,
  title          VARCHAR(400) NOT NULL,
  url            VARCHAR(600) NULL,
  summary        TEXT NULL,
  event_type     VARCHAR(24)  NULL,
  llm_summary    TEXT NULL,
  llm_confidence DOUBLE NULL,
  processed_at   DATETIME NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_hash (url_hash),
  KEY idx_pub (published_at),
  KEY idx_unprocessed (processed_at, published_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS headline_signals (
  headline_id BIGINT      NOT NULL,
  asset_code  VARCHAR(16) NOT NULL,
  tone        TINYINT     NOT NULL,          -- -2 (sangat bearish) .. +2 (sangat bullish)
  confidence  DOUBLE      NOT NULL,
  PRIMARY KEY (headline_id, asset_code),
  KEY idx_asset (asset_code),
  CONSTRAINT fk_signal_headline FOREIGN KEY (headline_id) REFERENCES headlines (id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------- hasil skor

CREATE TABLE IF NOT EXISTS factor_scores (
  asset_code VARCHAR(16) NOT NULL,
  as_of      DATE        NOT NULL,
  factor     VARCHAR(48) NOT NULL,
  raw_value  DOUBLE NULL,
  zscore     DOUBLE NULL,
  score      DOUBLE NULL,                    -- sudah dikali arah faktor
  weight     DOUBLE NOT NULL,
  status     VARCHAR(16) NOT NULL,           -- ok | missing | stale | error
  PRIMARY KEY (asset_code, as_of, factor)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS bias_scores (
  asset_code VARCHAR(16) NOT NULL,
  as_of      DATE        NOT NULL,
  total      DOUBLE      NOT NULL,           -- -1 .. +1
  bias       ENUM('bullish','bearish','neutral') NOT NULL,
  confidence DOUBLE      NOT NULL,           -- 0 .. 1 (heuristik, belum terkalibrasi)
  coverage   DOUBLE      NOT NULL,           -- porsi bobot faktor yang datanya tersedia
  details    JSON NULL,
  created_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (asset_code, as_of)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------- repricing

CREATE TABLE IF NOT EXISTS asset_betas (
  driver        VARCHAR(24) NOT NULL,
  target        VARCHAR(24) NOT NULL,
  regime        ENUM('all','supply','demand') NOT NULL,
  window_weeks  SMALLINT    NOT NULL,
  beta          DOUBLE NOT NULL,
  se            DOUBLE NOT NULL,             -- HAC (Newey-West)
  r2            DOUBLE NOT NULL,
  t_stat        DOUBLE NOT NULL,
  n_obs         INT    NOT NULL,
  beta_recent   DOUBLE NULL,                 -- 52 minggu terakhir
  noise_sigma   DOUBLE NULL,                 -- std residual mingguan
  decomposition JSON NULL,
  flags         JSON NULL,
  computed_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (driver, target, regime, window_weeks)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS scenario_runs (
  id         BIGINT NOT NULL AUTO_INCREMENT,
  created_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
  driver     VARCHAR(24) NOT NULL,
  baseline   DOUBLE NOT NULL,
  target     DOUBLE NULL,
  shock      DOUBLE NOT NULL,
  regime     VARCHAR(8)  NOT NULL,
  result     JSON NOT NULL,
  PRIMARY KEY (id),
  KEY idx_created (created_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------- operasional

CREATE TABLE IF NOT EXISTS engine_state (
  k          VARCHAR(48) NOT NULL,
  v          JSON NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (k)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS job_runs (
  id          BIGINT NOT NULL AUTO_INCREMENT,
  job         VARCHAR(32) NOT NULL,
  started_at  DATETIME NOT NULL,
  finished_at DATETIME NULL,
  status      VARCHAR(12) NOT NULL DEFAULT 'running',
  message     TEXT NULL,
  PRIMARY KEY (id),
  KEY idx_job (job, started_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS alerts_log (
  id         BIGINT NOT NULL AUTO_INCREMENT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  channel    VARCHAR(16) NOT NULL,
  kind       VARCHAR(24) NOT NULL,
  body       TEXT NOT NULL,
  ok         TINYINT(1) NOT NULL DEFAULT 1,
  PRIMARY KEY (id)
) ENGINE=InnoDB;
