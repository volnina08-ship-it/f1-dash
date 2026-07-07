-- APEXODDS normalized core schema (Supabase / Postgres)
-- Times are integer milliseconds (*_ms). Session keys follow
-- "{year}_{round:02d}_{session_type}", e.g. '2024_05_R'.
-- Apply with: python -m apexodds.data.db --init

create table if not exists events (
    meeting_key   text primary key,          -- "{year}_{round:02d}"
    year          int  not null,
    round         int  not null,
    circuit_id    text not null,
    name          text not null,
    country       text,
    date_start    date,
    date_end      date,
    unique (year, round)
);

create table if not exists sessions (
    session_key   text primary key,
    meeting_key   text references events (meeting_key),
    session_type  text not null,             -- FP1/FP2/FP3/Q/SQ/S/R
    total_laps    int,
    date_start    timestamptz
);

create table if not exists drivers (
    season        int  not null,
    driver_number int  not null,
    code          text not null,             -- VER, NOR, ...
    full_name     text,
    team          text,
    primary key (season, driver_number)
);

create table if not exists laps (
    session_key      text not null,
    driver_number    int  not null,
    lap_number       int  not null,
    code             text,
    team             text,
    lap_time_ms      bigint,
    s1_ms            bigint,
    s2_ms            bigint,
    s3_ms            bigint,
    is_pit_in        boolean default false,
    is_pit_out       boolean default false,
    compound         text,
    tyre_age         int,
    stint_id         int,
    track_status     text,
    position         int,
    fuel_corrected_ms bigint,                -- filled by the pace pipeline
    primary key (session_key, driver_number, lap_number)
);
create index if not exists laps_session_lap on laps (session_key, lap_number);

create table if not exists stints (
    session_key    text not null,
    driver_number  int  not null,
    stint_id       int  not null,
    compound       text not null,
    lap_start      int  not null,
    lap_end        int  not null,
    tyre_age_start int  default 0,
    primary key (session_key, driver_number, stint_id)
);

create table if not exists pitstops (
    session_key     text not null,
    driver_number   int  not null,
    lap             int  not null,
    pit_duration_ms bigint,                  -- stationary/pit-lane time when known
    total_loss_ms   bigint,                  -- full cost vs staying out (fitted)
    primary key (session_key, driver_number, lap)
);

create table if not exists race_control (
    id            bigint generated always as identity primary key,
    session_key   text not null,
    lap           int,
    category      text,
    flag          text,
    message       text,
    driver_number int
);
create index if not exists race_control_session on race_control (session_key, lap);

create table if not exists weather (
    id            bigint generated always as identity primary key,
    session_key   text not null,
    time_offset_s double precision,
    air_temp      double precision,
    track_temp    double precision,
    humidity      double precision,
    rainfall      boolean,
    wind_speed    double precision
);
create index if not exists weather_session on weather (session_key);

create table if not exists circuit_params (
    circuit_id             text primary key,
    name                   text,
    lap_count              int,
    pit_loss_s             double precision,
    pit_loss_std_s         double precision,
    sc_prob_race           double precision,  -- P(>=1 SC per race)
    vsc_prob_race          double precision,
    overtake_difficulty    double precision,  -- 0 (easy) .. 1 (Monaco)
    drs_zones              int,
    lap1_hazard_multiplier double precision
);

-- One row per (recalculation, driver): the probability layer's time series.
-- Backtests bulk-write these; Phase 1 appends live and the UI charts them.
create table if not exists sim_snapshots (
    session_key      text not null,
    lap              int  not null,
    driver_number    int  not null,
    code             text,
    team             text,
    current_position int,
    win_p            double precision,
    podium_p         double precision,
    top10_p          double precision,
    dnf_p            double precision,
    exp_finish       double precision,
    finish_p5        int,
    finish_p50       int,
    finish_p95       int,
    exp_points       double precision,
    pit_prob         double precision,
    pit_window_open  int,
    pit_window_p50   int,
    pit_window_close int,
    computed_at      timestamptz default now(),
    primary key (session_key, lap, driver_number)
);
create index if not exists sim_snapshots_session on sim_snapshots (session_key, lap);
