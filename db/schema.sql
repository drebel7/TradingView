-- ===========================================================================
-- analysis.db - baza wyników analiz sygnałów TradingView (schema v1)
-- ===========================================================================
-- Zasilanie:
--   scripts/db_init.py            - tworzy/migruje bazę z tego pliku
--   scripts/db_import_scripts.py  - kod skryptów, sygnały, warianty, parametry
--   scripts/db_import_analysis.py - surowe CSV z analysis/ -> runy + pomiary
-- Analiza:      scripts/db_query.py   (gotowe zapytania + SQL)
-- Weryfikacja:  scripts/db_verify.py  (widoki vs pliki *_SUMMARY*.csv)
--
-- Konwencje:
--   * czasy ISO-8601, np. '2026-10-14T09:03:13'
--   * pf = NULL gdy brak strat (w CSV: puste pole / znak nieskończoności)
--   * status pomiaru (measurement):
--       ok        - sygnał wystąpił (n > 0)
--       no_signal - symbol odczytany, sygnał nie wystąpił (n = 0 / brak metryk)
--       recovered - dane odzyskane z wiersza NO_DATA (--salvage-timeouts),
--                   świadomie POZA widokami podsumowań
--       fail      - inny błąd/scenariusz
--   * status symbolu w runie (run_symbol): ok | no_data | recovered | fail
--     (NO_DATA dotyczy całego symbolu, nie pojedynczego wariantu)
--   * wariant bez własnych parametrów ma params_source='script_defaults'
--     i params_json = NULL (parametry = domyślne inputy skryptu -> script_param)
-- ===========================================================================

PRAGMA foreign_keys = ON;

-- ===========================================================================
-- WYMIARY: skrypty
-- ===========================================================================

CREATE TABLE IF NOT EXISTS script (
    id            INTEGER PRIMARY KEY,
    path          TEXT    NOT NULL UNIQUE,   -- ścieżka relatywna do repo
    kind          TEXT    NOT NULL CHECK (kind IN ('indicator','library','strategy','other')),
    title         TEXT,
    shorttitle    TEXT,
    pine_version  TEXT,
    sha256        TEXT    NOT NULL,
    git_commit    TEXT,
    code          TEXT    NOT NULL,
    imported_at   TEXT    NOT NULL
);

-- Historia wersji kodu (append-only). run.script_revision_id wskazuje wersję,
-- która wyliczyła dany pomiar.
CREATE TABLE IF NOT EXISTS script_revision (
    id            INTEGER PRIMARY KEY,
    script_id     INTEGER NOT NULL REFERENCES script(id),
    sha256        TEXT    NOT NULL,
    git_commit    TEXT,
    code          TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    UNIQUE (script_id, sha256)
);

-- Zależności między skryptami (import bibliotek: import drebel/DRELib/39 as drelib)
CREATE TABLE IF NOT EXISTS script_dependency (
    id            INTEGER PRIMARY KEY,
    script_id     INTEGER NOT NULL REFERENCES script(id),
    alias         TEXT    NOT NULL,          -- drelib, dreperf
    lib_name      TEXT    NOT NULL,          -- DRELib, DREPerf
    lib_version   TEXT,                      -- 39, 27 (wersja z deklaracji import)
    lib_script_id INTEGER REFERENCES script(id),
    UNIQUE (script_id, alias)
);

-- Inputy skryptu (defval) - konfiguracja pomiaru wspólna dla jego wariantów
CREATE TABLE IF NOT EXISTS script_param (
    id            INTEGER PRIMARY KEY,
    script_id     INTEGER NOT NULL REFERENCES script(id),
    name          TEXT    NOT NULL,          -- np. iSigCheckTime
    type          TEXT,                      -- int, float, bool, string, color, ...
    title         TEXT,
    group_name    TEXT,
    value_num     REAL,
    value_bool    INTEGER,
    value_text    TEXT,
    UNIQUE (script_id, name)
);

-- ===========================================================================
-- WYMIARY: sygnały i warianty
-- ===========================================================================

-- Sygnał bazowy. Skrypt bazowy (ETSB) definiuje po jednym sygnale na nazwę
-- z tabeli (et3sb, CapLow, ...); skrypty perf_opt_* definiują JEDEN sygnał
-- bazowy (np. CapLow) i wiele wariantów parametryzowanych.
CREATE TABLE IF NOT EXISTS signal (
    id            INTEGER PRIMARY KEY,
    script_id     INTEGER NOT NULL REFERENCES script(id),
    code          TEXT    NOT NULL,          -- 'CapLow', 'WON:turnUp'
    name          TEXT,
    family        TEXT,                      -- rezerwa na grupowanie sygnałów
    UNIQUE (script_id, code)
);

-- Konkretna nazwa sygnału z kolumny 'sig' tabeli wskaźnika (i z CSV).
-- role:
--   original   - sygnał oryginalny (skrypt bazowy, np. ETSB): parametry = domyślne
--                inputy skryptu (params_source='script_defaults'),
--   equivalent - wariant przeglądu replikujący oryginał (z komentarza
--                "Sanity check: X == original default"),
--   variant    - pozostały wariant parametryczny.
CREATE TABLE IF NOT EXISTS variant (
    id            INTEGER PRIMARY KEY,
    signal_id     INTEGER NOT NULL REFERENCES signal(id),
    sig_name      TEXT    NOT NULL UNIQUE,   -- 'capLowTTT_95'
    role          TEXT    NOT NULL CHECK (role IN
                          ('original','equivalent','variant')),
    params_source TEXT    NOT NULL CHECK (params_source IN
                          ('pine_parse','script_defaults','manual','unknown')),
    params_json   TEXT,                      -- {"minVolPct": 95, "volAboveAvg": true}
    notes         TEXT
);

-- Znormalizowane parametry wariantu (z params_json), do filtrowania w SQL
CREATE TABLE IF NOT EXISTS variant_param (
    variant_id    INTEGER NOT NULL REFERENCES variant(id),
    name          TEXT    NOT NULL,
    type          TEXT    NOT NULL CHECK (type IN ('num','bool','text')),
    value_num     REAL,
    value_bool    INTEGER,
    value_text    TEXT,
    PRIMARY KEY (variant_id, name)
);

-- ===========================================================================
-- WYMIARY: uniwersa i spółki
-- ===========================================================================

CREATE TABLE IF NOT EXISTS universe (
    id            INTEGER PRIMARY KEY,
    code          TEXT    NOT NULL UNIQUE,   -- GPW_NC, US_BIG
    watchlist_path TEXT,
    description   TEXT
);

CREATE TABLE IF NOT EXISTS instrument (
    id            INTEGER PRIMARY KEY,
    ticker        TEXT    NOT NULL UNIQUE,   -- 'GPW:AQU', 'NASDAQ:GOOGL'
    exchange      TEXT                       -- 'GPW', 'NASDAQ'
);

-- Aktualny skład uniwersum
CREATE TABLE IF NOT EXISTS universe_member (
    universe_id        INTEGER NOT NULL REFERENCES universe(id),
    instrument_id      INTEGER NOT NULL REFERENCES instrument(id),
    first_seen_run_id  INTEGER REFERENCES run(id),
    last_seen_run_id   INTEGER REFERENCES run(id),
    PRIMARY KEY (universe_id, instrument_id)
);

-- Grupy z watchlisty, do których należy spółka (ticker może być w kilku,
-- np. US: GOOGL w "FAANG" i w "AI")
CREATE TABLE IF NOT EXISTS universe_member_group (
    universe_id    INTEGER NOT NULL REFERENCES universe(id),
    instrument_id  INTEGER NOT NULL REFERENCES instrument(id),
    grp            TEXT    NOT NULL,
    PRIMARY KEY (universe_id, instrument_id, grp)
);

-- Cechy spółki z tabeli wskaźnika "DRE Info" (wolnozmienne)
CREATE TABLE IF NOT EXISTS company_profile (
    instrument_id  INTEGER PRIMARY KEY REFERENCES instrument(id),
    sector         TEXT,
    industry       TEXT,
    bench_index    TEXT,                     -- 'WIG', 'S&P 500'
    years_on_exchange INTEGER,
    updated_at     TEXT
);

-- Pomiary spółki z tabeli "DRE Info" (snapshot dzienny).
-- Uwaga: wiersze "LoD price", "LoD dist. [%]", "Dtt vol. [%] (proj.)" i
-- "Dtt time [%]" są świadomie poza bazą (nadal widoczne na wykresie i w CSV).
CREATE TABLE IF NOT EXISTS company_metric (
    instrument_id      INTEGER NOT NULL REFERENCES instrument(id),
    snapshot_date      TEXT    NOT NULL,     -- 'YYYY-MM-DD'
    run_id             INTEGER REFERENCES run(id),
    market_cap_m       REAL,                 -- kapitalizacja w mln (waluta instrumentu)
    adr_pct            REAL,
    atr                REAL,
    avg_turnover_m     REAL,
    hod_price          REAL,
    ma_dist_prctl      TEXT,                 -- '82/71/55/40'
    sharpe             REAL,
    eps_up_1y          INTEGER,
    eps_days_1y        INTEGER,
    eps_up_2y          INTEGER,
    eps_days_2y        INTEGER,
    n_broken_extremes_pct REAL,
    n_broken_mod       TEXT,                 -- '+', '0', '-'
    bench_mod          TEXT,                 -- '(++)', '(+)', '(0)', '(-)', '(--)'
    config_json        TEXT,
    PRIMARY KEY (instrument_id, snapshot_date)
);

-- ===========================================================================
-- FAKTY: runy i pomiary
-- ===========================================================================

-- Pojedynczy scrape (jeden plik CSV): uniwersum x skrypt x data
CREATE TABLE IF NOT EXISTS run (
    id                  INTEGER PRIMARY KEY,
    started_at          TEXT    NOT NULL,    -- '# generated:' z nagłówka CSV
    finished_at         TEXT,                -- 'updated' z pliku progress
    universe_id         INTEGER REFERENCES universe(id),
    script_id           INTEGER REFERENCES script(id),
    script_revision_id  INTEGER REFERENCES script_revision(id),
    indicator_title     TEXT,                -- '# indicator:'
    resolution          TEXT,
    watchlist_path      TEXT,                -- '# watchlist:'
    watchlist_sha256    TEXT,
    scraper_version     TEXT,
    config_json         TEXT,                -- inputy skryptu w momencie runu
    ok                  INTEGER,             -- liczba symboli OK (z progress)
    fail                INTEGER,             -- liczba porażek (z progress)
    out_csv             TEXT    NOT NULL UNIQUE,  -- klucz naturalny (idempotencja)
    notes               TEXT
);

-- Wynik scrapowania symbolu w runie (niezależny od wariantów; NO_DATA tutaj)
CREATE TABLE IF NOT EXISTS run_symbol (
    run_id        INTEGER NOT NULL REFERENCES run(id),
    instrument_id INTEGER NOT NULL REFERENCES instrument(id),
    grp           TEXT    NOT NULL DEFAULT '',
    status        TEXT    NOT NULL CHECK (status IN
                          ('ok','no_data','recovered','fail')),
    note          TEXT,                      -- komunikat błędu / kontekst
    PRIMARY KEY (run_id, instrument_id, grp)
);

-- Wynik jednego wariantu dla jednej spółki w jednym runie.
-- Klucz zawiera `grp`, bo ten sam ticker może być w kilku grupach watchlisty
-- i scraper zapisuje wiersz na każdą grupę (pomiar 1:1 z plikiem CSV;
-- do statystyk per spółka służy widok v_measurement_uniq).
CREATE TABLE IF NOT EXISTS measurement (
    run_id        INTEGER NOT NULL REFERENCES run(id),
    instrument_id INTEGER NOT NULL REFERENCES instrument(id),
    variant_id    INTEGER NOT NULL REFERENCES variant(id),
    grp           TEXT    NOT NULL DEFAULT '',
    status        TEXT    NOT NULL CHECK (status IN
                          ('ok','no_signal','recovered','fail')),
    n             INTEGER,
    win_pct       REAL,
    avg_r         REAL,
    pf            REAL,
    max_dd        REAL,
    score         REAL,
    sum_win_r     REAL,
    sum_loss_r    REAL,
    raw           TEXT,                      -- komunikat błędu / wiersz tabeli (diagnostyka)
    PRIMARY KEY (run_id, instrument_id, variant_id, grp)
);

CREATE INDEX IF NOT EXISTS idx_measurement_variant    ON measurement(variant_id);
CREATE INDEX IF NOT EXISTS idx_measurement_run_status ON measurement(run_id, status);
CREATE INDEX IF NOT EXISTS idx_measurement_instrument ON measurement(instrument_id);
CREATE INDEX IF NOT EXISTS idx_run_symbol_status      ON run_symbol(status);
CREATE INDEX IF NOT EXISTS idx_variant_signal         ON variant(signal_id);
CREATE INDEX IF NOT EXISTS idx_variant_param_name     ON variant_param(name);
CREATE INDEX IF NOT EXISTS idx_run_universe_script    ON run(universe_id, script_id, started_at);
CREATE INDEX IF NOT EXISTS idx_company_metric_date    ON company_metric(snapshot_date);

-- ===========================================================================
-- WIDOKI
-- ===========================================================================
-- Widoki są przy każdym uruchomieniu db_init.py odtwarzane (DROP + CREATE),
-- żeby zmiana definicji w tym pliku trafiała także do istniejącej bazy
-- (CREATE VIEW IF NOT EXISTS sam tego nie zrobi).
DROP VIEW IF EXISTS v_run_latest;
DROP VIEW IF EXISTS v_measurement_latest;
DROP VIEW IF EXISTS v_measurement_ok;
DROP VIEW IF EXISTS v_measurement_uniq;
DROP VIEW IF EXISTS v_measurement_recovered;
DROP VIEW IF EXISTS v_run_gaps;
DROP VIEW IF EXISTS v_instrument_company;
DROP VIEW IF EXISTS v_company_card;
DROP VIEW IF EXISTS v_company_signal;
DROP VIEW IF EXISTS v_signal_summary_scope;
DROP VIEW IF EXISTS v_signal_summary;
DROP VIEW IF EXISTS v_signal_summary_latest;
DROP VIEW IF EXISTS v_signal_summary_all;
DROP VIEW IF EXISTS v_signal_by_mcap;
DROP VIEW IF EXISTS v_signal_by_sector;
DROP VIEW IF EXISTS v_baseline_vs_best;
DROP VIEW IF EXISTS v_variant_params;

-- Spółka + jej najnowszy snapshot DRE Info + cechy, z kubełkiem kapitalizacji.
-- Kubełki (w milionach waluty instrumentu): micro <50, small <200, mid <1000,
-- large <10000, mega >=10000, unknown = brak danych o akcjach.
CREATE VIEW IF NOT EXISTS v_instrument_company AS
SELECT
    i.id AS instrument_id,
    i.ticker,
    i.exchange,
    cm.snapshot_date,
    cm.market_cap_m,
    cm.adr_pct,
    cm.atr,
    cm.avg_turnover_m,
    cm.hod_price,
    cm.ma_dist_prctl,
    cm.sharpe,
    cm.eps_up_1y,
    cm.eps_days_1y,
    cm.eps_up_2y,
    cm.eps_days_2y,
    cm.n_broken_extremes_pct,
    cm.n_broken_mod,
    cm.bench_mod,
    p.sector,
    p.industry,
    p.bench_index,
    p.years_on_exchange,
    CASE
        WHEN cm.market_cap_m IS NULL THEN 'unknown'
        WHEN cm.market_cap_m <    50 THEN 'micro'
        WHEN cm.market_cap_m <   200 THEN 'small'
        WHEN cm.market_cap_m <  1000 THEN 'mid'
        WHEN cm.market_cap_m < 10000 THEN 'large'
        ELSE 'mega'
    END AS mcap_bucket,
    CASE
        WHEN cm.market_cap_m IS NULL THEN 0
        WHEN cm.market_cap_m <    50 THEN 1
        WHEN cm.market_cap_m <   200 THEN 2
        WHEN cm.market_cap_m <  1000 THEN 3
        WHEN cm.market_cap_m < 10000 THEN 4
        ELSE 5
    END AS mcap_bucket_ord
FROM instrument i
LEFT JOIN company_metric cm ON cm.instrument_id = i.id
     AND cm.snapshot_date = (SELECT MAX(snapshot_date) FROM company_metric
                             WHERE instrument_id = i.id)
LEFT JOIN company_profile p ON p.instrument_id = i.id;

-- Najnowszy run per (uniwersum, skrypt)
CREATE VIEW IF NOT EXISTS v_run_latest AS
SELECT id, started_at, finished_at, universe_id, script_id, script_revision_id,
       indicator_title, resolution, watchlist_path, watchlist_sha256,
       scraper_version, config_json, ok, fail, out_csv, notes
FROM (
    SELECT r.*, ROW_NUMBER() OVER (
               PARTITION BY r.universe_id, r.script_id
               ORDER BY r.started_at DESC, r.id DESC) AS rn
    FROM run r
)
WHERE rn = 1;

-- Pomiary wyłącznie z najnowszych runów (per uniwersum i skrypt)
CREATE VIEW IF NOT EXISTS v_measurement_latest AS
SELECT m.*
FROM measurement m
JOIN v_run_latest l ON l.id = m.run_id;

-- Tylko pomiary, w których sygnał wystąpił (zgodne z plikami SUMMARY)
CREATE VIEW IF NOT EXISTS v_measurement_ok AS
SELECT * FROM measurement WHERE status = 'ok' AND n > 0;

-- Pomiary zdeduplikowane do jednej spółki na wariant i run (spółka może być
-- w kilku grupach watchlisty). Do statystyk liczbowych per spółka.
CREATE VIEW IF NOT EXISTS v_measurement_uniq AS
SELECT run_id, instrument_id, variant_id, MIN(grp) AS grp, status, n,
       win_pct, avg_r, pf, max_dd, score, sum_win_r, sum_loss_r, raw
FROM measurement
GROUP BY run_id, instrument_id, variant_id;

-- Pomiary odzyskane z timeoutów (poza podsumowaniami)
CREATE VIEW IF NOT EXISTS v_measurement_recovered AS
SELECT * FROM measurement WHERE status = 'recovered';

-- Symbole nieodczytane w runach (luki danych)
CREATE VIEW IF NOT EXISTS v_run_gaps AS
SELECT rs.run_id, r.started_at, u.code AS universe, r.indicator_title,
       i.ticker, rs.grp, rs.status, rs.note
FROM run_symbol rs
JOIN run r        ON r.id = rs.run_id
JOIN instrument i ON i.id = rs.instrument_id
LEFT JOIN universe u ON u.id = r.universe_id
WHERE rs.status <> 'ok';

-- ---------------------------------------------------------------------------
-- Agregacja sygnałów w czterech zakresach (kolumna `scope`):
--   'run:<id>'  - per run (odpowiednik plików <UNIWERSUM>_<SIG>_SUMMARY.csv)
--   'latest'    - po najnowszych runach wszystkich uniwersów
--                 (odpowiednik plików *_SUMMARY_ALL.csv)
--   'mcap'      - po najnowszych runach, w podziale na uniwersum (dim1)
--                 i kubełek kapitalizacji (dim2)
--   'sector'    - po najnowszych runach, w podziale na uniwersum (dim1)
--                 i sektor (dim2)
-- Logika 1:1 z scripts/summarize_signals.py. Pomiary 'recovered' (odzyskane
-- z timeoutów) są świadomie poza podsumowaniami.
-- ---------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_signal_summary_scope AS
WITH scoped AS (
    SELECT m.*, 'run:' || m.run_id AS scope, NULL AS dim1, NULL AS dim2
    FROM measurement m
    WHERE m.status IN ('ok','no_signal')
    UNION ALL
    SELECT m.*, 'latest', NULL, NULL
    FROM measurement m
    JOIN v_run_latest l ON l.id = m.run_id
    WHERE m.status IN ('ok','no_signal')
    UNION ALL
    SELECT m.*, 'mcap', u.code, COALESCE(c.mcap_bucket, 'unknown')
    FROM measurement m
    JOIN v_run_latest l ON l.id = m.run_id
    LEFT JOIN run r ON r.id = m.run_id
    LEFT JOIN universe u ON u.id = r.universe_id
    LEFT JOIN v_instrument_company c ON c.instrument_id = m.instrument_id
    WHERE m.status IN ('ok','no_signal')
    UNION ALL
    SELECT m.*, 'sector', u.code, COALESCE(c.sector, 'unknown')
    FROM measurement m
    JOIN v_run_latest l ON l.id = m.run_id
    LEFT JOIN run r ON r.id = m.run_id
    LEFT JOIN universe u ON u.id = r.universe_id
    LEFT JOIN v_instrument_company c ON c.instrument_id = m.instrument_id
    WHERE m.status IN ('ok','no_signal')
),
agg AS (
    SELECT
        scope,
        dim1,
        dim2,
        variant_id,
        COUNT(CASE WHEN status = 'ok' THEN 1 END)                            AS symbols,
        CAST(COALESCE(SUM(CASE WHEN status = 'ok' THEN n END), 0) AS INTEGER) AS occurrences,
        SUM(CASE WHEN status = 'ok' AND win_pct IS NOT NULL THEN win_pct * n END)
            / NULLIF(SUM(CASE WHEN status = 'ok' THEN n END), 0)             AS win_pct,
        SUM(CASE WHEN status = 'ok' AND avg_r IS NOT NULL THEN avg_r * n END)
            / NULLIF(SUM(CASE WHEN status = 'ok' THEN n END), 0)             AS avg_r,
        CASE
            WHEN COUNT(sum_win_r) > 0 OR COUNT(sum_loss_r) > 0 THEN
                CASE WHEN COALESCE(SUM(sum_loss_r), 0) < 0
                     THEN SUM(sum_win_r) / ABS(SUM(sum_loss_r)) END
            WHEN SUM(CASE WHEN status = 'ok' AND pf IS NOT NULL THEN n END) > 0
                THEN SUM(CASE WHEN status = 'ok' AND pf IS NOT NULL THEN pf * n END)
                     / SUM(CASE WHEN status = 'ok' AND pf IS NOT NULL THEN n END)
        END                                                                  AS pf,
        SUM(CASE WHEN status = 'ok' AND max_dd IS NOT NULL THEN max_dd * n END)
            / NULLIF(SUM(CASE WHEN status = 'ok' THEN n END), 0)             AS max_dd,
        AVG(CASE WHEN status = 'ok' THEN score END)                          AS score_mean,
        SUM(CASE WHEN status = 'ok' THEN score END)                          AS score_sum,
        COUNT(CASE WHEN status = 'ok' AND score IS NOT NULL THEN 1 END)      AS score_cnt,
        COUNT(CASE WHEN status = 'ok' AND score > 0 THEN 1 END)              AS score_pos_cnt,
        SUM(sum_win_r)                                                       AS gross_win_r,
        SUM(sum_loss_r)                                                      AS gross_loss_r,
        MAX(CASE WHEN sum_win_r IS NOT NULL OR sum_loss_r IS NOT NULL
                 THEN 1 ELSE 0 END)                                          AS has_gross
    FROM scoped
    GROUP BY scope, dim1, dim2, variant_id
),
median_avg_r AS (
    SELECT scope, dim1, dim2, variant_id, AVG(x) AS median_avg_r
    FROM (
        SELECT scope, dim1, dim2, variant_id, avg_r AS x,
               ROW_NUMBER() OVER (PARTITION BY scope, dim1, dim2, variant_id
                                  ORDER BY avg_r) AS rn,
               COUNT(*)     OVER (PARTITION BY scope, dim1, dim2, variant_id) AS cnt
        FROM scoped
        WHERE status = 'ok' AND avg_r IS NOT NULL
    )
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY scope, dim1, dim2, variant_id
),
median_pf AS (
    SELECT scope, dim1, dim2, variant_id, AVG(x) AS median_pf
    FROM (
        SELECT scope, dim1, dim2, variant_id, sum_win_r / ABS(sum_loss_r) AS x,
               ROW_NUMBER() OVER (PARTITION BY scope, dim1, dim2, variant_id
                                  ORDER BY sum_win_r / ABS(sum_loss_r)) AS rn,
               COUNT(*)     OVER (PARTITION BY scope, dim1, dim2, variant_id) AS cnt
        FROM scoped
        WHERE sum_win_r IS NOT NULL AND sum_loss_r IS NOT NULL AND sum_loss_r < 0
    )
    WHERE rn IN ((cnt + 1) / 2, (cnt + 2) / 2)
    GROUP BY scope, dim1, dim2, variant_id
)
SELECT
    a.scope,
    a.dim1,
    a.dim2,
    a.variant_id,
    a.symbols,
    a.occurrences,
    a.win_pct,
    a.avg_r,
    a.pf,
    a.max_dd,
    a.score_mean,
    a.score_sum,
    100.0 * a.score_pos_cnt / NULLIF(a.score_cnt, 0) AS score_pos_pct,
    m1.median_avg_r,
    m2.median_pf,
    a.gross_win_r,
    a.gross_loss_r,
    a.has_gross
FROM agg a
LEFT JOIN median_avg_r m1 ON m1.scope = a.scope AND m1.dim1 IS a.dim1
                         AND m1.dim2 IS a.dim2 AND m1.variant_id = a.variant_id
LEFT JOIN median_pf    m2 ON m2.scope = a.scope AND m2.dim1 IS a.dim1
                         AND m2.dim2 IS a.dim2 AND m2.variant_id = a.variant_id;

-- Podsumowanie per run (kolumny 1:1 jak w plikach <UNIWERSUM>_<SIG>_SUMMARY.csv)
CREATE VIEW IF NOT EXISTS v_signal_summary AS
SELECT
    CAST(substr(sc.scope, 5) AS INTEGER) AS run_id,
    r.started_at,
    r.universe_id,
    u.code        AS universe,
    r.script_id,
    r.indicator_title,
    sc.variant_id,
    v.sig_name,
    s.code        AS signal_code,
    v.role,
    sc.symbols,
    sc.occurrences,
    sc.win_pct,
    sc.avg_r,
    sc.pf,
    sc.max_dd,
    sc.score_mean,
    sc.score_sum,
    sc.score_pos_pct,
    sc.median_avg_r,
    sc.median_pf,
    sc.gross_win_r,
    sc.gross_loss_r
FROM v_signal_summary_scope sc
JOIN variant v ON v.id = sc.variant_id
JOIN signal  s ON s.id = v.signal_id
JOIN run     r ON r.id = CAST(substr(sc.scope, 5) AS INTEGER)
LEFT JOIN universe u ON u.id = r.universe_id
WHERE sc.scope LIKE 'run:%';

-- Podsumowanie z najnowszych runów (per uniwersum)
CREATE VIEW IF NOT EXISTS v_signal_summary_latest AS
SELECT s.*
FROM v_signal_summary s
JOIN v_run_latest l ON l.id = s.run_id;

-- Podsumowanie po wszystkich uniwersach (odpowiednik *_SUMMARY_ALL.csv)
CREATE VIEW IF NOT EXISTS v_signal_summary_all AS
SELECT
    sc.variant_id,
    v.sig_name,
    s.code        AS signal_code,
    v.role,
    sc.symbols,
    sc.occurrences,
    sc.win_pct,
    sc.avg_r,
    sc.pf,
    sc.max_dd,
    sc.score_mean,
    sc.score_sum,
    sc.score_pos_pct,
    sc.median_avg_r,
    sc.median_pf,
    sc.gross_win_r,
    sc.gross_loss_r
FROM v_signal_summary_scope sc
JOIN variant v ON v.id = sc.variant_id
JOIN signal  s ON s.id = v.signal_id
WHERE sc.scope = 'latest';

-- Sygnał bazowy vs najlepszy wariant (jak scripts/compare_signal_variants.py):
--   baseline_*  - sygnał oryginalny (role='original', ze skryptu bazowego),
--   equiv_*     - wariant replikujący oryginał (role='equivalent'),
--   best_*      - najwyższy score_mean wśród wariantów przeglądu,
--   best_robust_* - najwyższy score_mean przy occurrence >= 30% maksimum.
CREATE VIEW IF NOT EXISTS v_baseline_vs_best AS
WITH latest AS (
    SELECT universe, signal_code, sig_name, role, started_at, symbols, occurrences,
           win_pct, avg_r, pf, score_mean, score_pos_pct, median_avg_r, median_pf,
           MAX(occurrences) OVER (PARTITION BY universe, signal_code) AS max_occ
    FROM v_signal_summary_latest
    WHERE occurrences > 0
),
ranked AS (
    SELECT l.*,
           ROW_NUMBER() OVER (PARTITION BY universe, signal_code
                              ORDER BY score_mean DESC, occurrences DESC, sig_name) AS rn_sc,
           ROW_NUMBER() OVER (PARTITION BY universe, signal_code
                              ORDER BY CASE WHEN occurrences >= 0.30 * max_occ
                                            THEN score_mean END DESC,
                                       occurrences DESC, sig_name) AS rn_rob
    FROM latest l
    WHERE l.role <> 'original'
),
equiv AS (
    SELECT l.*,
           ROW_NUMBER() OVER (PARTITION BY universe, signal_code
                              ORDER BY sig_name) AS rn_eq
    FROM latest l
    WHERE l.role = 'equivalent'
)
SELECT
    b.universe,
    b.signal_code,
    b.started_at        AS baseline_started_at,
    b.sig_name          AS baseline_sig,
    b.symbols           AS baseline_symbols,
    b.occurrences       AS baseline_occ,
    b.win_pct           AS baseline_win_pct,
    b.avg_r             AS baseline_avg_r,
    b.pf                AS baseline_pf,
    b.score_mean        AS baseline_score,
    b.score_pos_pct     AS baseline_score_pos_pct,
    b.median_avg_r      AS baseline_median_avg_r,
    b.median_pf         AS baseline_median_pf,
    eq.sig_name         AS equiv_sig,
    eq.started_at       AS equiv_started_at,
    eq.symbols          AS equiv_symbols,
    eq.occurrences      AS equiv_occ,
    eq.win_pct          AS equiv_win_pct,
    eq.avg_r            AS equiv_avg_r,
    eq.pf               AS equiv_pf,
    eq.score_mean       AS equiv_score,
    eq.score_pos_pct    AS equiv_score_pos_pct,
    bs.started_at       AS best_started_at,
    bs.sig_name         AS best_sig,
    bs.symbols          AS best_symbols,
    bs.occurrences      AS best_occ,
    bs.win_pct          AS best_win_pct,
    bs.avg_r            AS best_avg_r,
    bs.pf               AS best_pf,
    bs.score_mean       AS best_score,
    bs.score_pos_pct    AS best_score_pos_pct,
    bs.median_avg_r     AS best_median_avg_r,
    bs.median_pf        AS best_median_pf,
    br.sig_name         AS best_robust_sig,
    br.occurrences      AS best_robust_occ,
    br.score_mean       AS best_robust_score
FROM (SELECT * FROM latest WHERE role = 'original') b
LEFT JOIN (SELECT * FROM equiv WHERE rn_eq = 1) eq
       ON eq.universe = b.universe AND eq.signal_code = b.signal_code
LEFT JOIN (SELECT * FROM ranked WHERE rn_sc = 1) bs
       ON bs.universe = b.universe AND bs.signal_code = b.signal_code
LEFT JOIN (SELECT * FROM ranked WHERE rn_rob = 1) br
       ON br.universe = b.universe AND br.signal_code = b.signal_code;

-- Parametry wariantu w formie tekstowej (do szybkiego podglądu)
CREATE VIEW IF NOT EXISTS v_variant_params AS
SELECT variant_id, sig_name, GROUP_CONCAT(txt, ', ') AS params
FROM (
    SELECT vp.variant_id,
           v.sig_name,
           vp.name || '=' ||
             COALESCE(CAST(vp.value_num AS TEXT),
                      CASE vp.value_bool WHEN 1 THEN 'true' WHEN 0 THEN 'false' END,
                      vp.value_text) AS txt
    FROM variant_param vp
    JOIN variant v ON v.id = vp.variant_id
    ORDER BY vp.variant_id, vp.name
)
GROUP BY variant_id, sig_name;

-- Karta spółki: instrument + profil + najnowszy pomiar DRE Info (+ kubełek MCap)
CREATE VIEW IF NOT EXISTS v_company_card AS
SELECT instrument_id, ticker, exchange, sector, industry, bench_index,
       years_on_exchange, snapshot_date, market_cap_m, adr_pct, atr,
       avg_turnover_m, hod_price, ma_dist_prctl, sharpe, eps_up_1y, eps_days_1y,
       eps_up_2y, eps_days_2y, n_broken_extremes_pct, n_broken_mod, bench_mod,
       mcap_bucket, mcap_bucket_ord
FROM v_instrument_company;

-- Pomiary sygnałów wzbogacone danymi spółki (fundamenty z DRE Info).
-- Jedna spółka może mieć kilka wierszy (grupy watchlisty) - do statystyk
-- "na spółkę" użyj v_measurement_uniq albo DISTINCT po (run_id, ticker, sig_name).
CREATE VIEW IF NOT EXISTS v_company_signal AS
SELECT
    m.run_id,
    r.started_at,
    r.indicator_title,
    u.code            AS universe,
    s.code            AS signal_code,
    v.sig_name,
    v.role,
    v.id              AS variant_id,
    c.instrument_id,
    c.ticker,
    c.exchange,
    m.grp,
    m.status,
    m.n,
    m.win_pct,
    m.avg_r,
    m.pf,
    m.max_dd,
    m.score,
    m.sum_win_r,
    m.sum_loss_r,
    c.snapshot_date,
    c.market_cap_m,
    c.mcap_bucket,
    c.mcap_bucket_ord,
    c.adr_pct,
    c.atr,
    c.avg_turnover_m,
    c.hod_price,
    c.ma_dist_prctl,
    c.sharpe,
    c.eps_up_1y,
    c.eps_days_1y,
    c.eps_up_2y,
    c.eps_days_2y,
    c.n_broken_extremes_pct,
    c.n_broken_mod,
    c.bench_mod,
    c.sector,
    c.industry,
    c.bench_index,
    c.years_on_exchange
FROM measurement m
JOIN run r ON r.id = m.run_id
JOIN variant v ON v.id = m.variant_id
JOIN signal s ON s.id = v.signal_id
LEFT JOIN universe u ON u.id = r.universe_id
JOIN v_instrument_company c ON c.instrument_id = m.instrument_id;

-- Wyniki sygnałów w podziale na kubełek kapitalizacji spółki
-- (najnowsze runy; agregacja jak w v_signal_summary_*).
CREATE VIEW IF NOT EXISTS v_signal_by_mcap AS
SELECT
    sc.dim1 AS universe,
    sc.dim2 AS mcap_bucket,
    CASE sc.dim2
        WHEN 'micro' THEN 1 WHEN 'small' THEN 2 WHEN 'mid' THEN 3
        WHEN 'large' THEN 4 WHEN 'mega' THEN 5 ELSE 0
    END AS mcap_bucket_ord,
    sc.variant_id,
    s.code  AS signal_code,
    v.sig_name,
    v.role,
    sc.symbols,
    sc.occurrences,
    sc.win_pct,
    sc.avg_r,
    sc.pf,
    sc.max_dd,
    sc.score_mean,
    sc.score_sum,
    sc.score_pos_pct,
    sc.median_avg_r,
    sc.median_pf,
    sc.gross_win_r,
    sc.gross_loss_r
FROM v_signal_summary_scope sc
JOIN variant v ON v.id = sc.variant_id
JOIN signal s ON s.id = v.signal_id
WHERE sc.scope = 'mcap';

-- Wyniki sygnałów w podziale na sektor spółki (najnowsze runy)
CREATE VIEW IF NOT EXISTS v_signal_by_sector AS
SELECT
    sc.dim1 AS universe,
    sc.dim2 AS sector,
    sc.variant_id,
    s.code  AS signal_code,
    v.sig_name,
    v.role,
    sc.symbols,
    sc.occurrences,
    sc.win_pct,
    sc.avg_r,
    sc.pf,
    sc.max_dd,
    sc.score_mean,
    sc.score_sum,
    sc.score_pos_pct,
    sc.median_avg_r,
    sc.median_pf,
    sc.gross_win_r,
    sc.gross_loss_r
FROM v_signal_summary_scope sc
JOIN variant v ON v.id = sc.variant_id
JOIN signal s ON s.id = v.signal_id
WHERE sc.scope = 'sector';
