-- ShortTrip on openGauss / GaussDB. Runs inside the schema named by SHORTTRIP_DB_SCHEMA.
-- Every statement is idempotent; db.ensure_schema() records the version in st_meta.

-- ============================================================ accounts
CREATE TABLE IF NOT EXISTS st_user (
    id              BIGSERIAL PRIMARY KEY,
    username        VARCHAR(32)  NOT NULL UNIQUE,
    display_name    VARCHAR(64)  NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(16)  NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    failed_logins   INT          NOT NULL DEFAULT 0,
    locked_until    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_login_at   TIMESTAMPTZ
);

-- Only the SHA-256 of the session token is stored; the token itself lives in the client cookie.
CREATE TABLE IF NOT EXISTS st_session (
    token_hash      VARCHAR(64)  PRIMARY KEY,
    user_id         BIGINT       NOT NULL REFERENCES st_user(id) ON DELETE CASCADE,
    client          VARCHAR(16)  NOT NULL CHECK (client IN ('pc', 'android')),
    user_agent      VARCHAR(256),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ  NOT NULL
);
CREATE INDEX IF NOT EXISTS st_session_user ON st_session(user_id);

CREATE TABLE IF NOT EXISTS st_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT,
    action          VARCHAR(48)  NOT NULL,
    detail          TEXT,
    client          VARCHAR(16),
    remote_addr     VARCHAR(64),
    at              TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS st_audit_user_at ON st_audit_log(user_id, at);

-- ============================================================ content-addressed file store
-- A blob is stored once per SHA-256, split into chunks so no single BYTEA value gets huge.
CREATE TABLE IF NOT EXISTS st_blob (
    sha256          VARCHAR(64)  PRIMARY KEY,
    size            BIGINT       NOT NULL,
    chunk_count     INT          NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS st_blob_chunk (
    sha256          VARCHAR(64)  NOT NULL REFERENCES st_blob(sha256) ON DELETE CASCADE,
    seq             INT          NOT NULL,
    data            BYTEA        NOT NULL,
    PRIMARY KEY (sha256, seq)
);

-- ============================================================ travel data snapshots (one row per data version)
CREATE TABLE IF NOT EXISTS st_snapshot (
    id              VARCHAR(64)  PRIMARY KEY,
    commit_sha      VARCHAR(40),
    profile         VARCHAR(128),
    depends_on      VARCHAR(64)  REFERENCES st_snapshot(id),
    manifest_sha256 VARCHAR(64)  NOT NULL,
    file_count      INT          NOT NULL,
    total_bytes     BIGINT       NOT NULL,
    stored_bytes    BIGINT       NOT NULL,
    note            VARCHAR(256),
    imported_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
-- derived_from = 'gunzip:<path>' means the file is rebuilt from another stored file of the snapshot.
CREATE TABLE IF NOT EXISTS st_snapshot_file (
    snapshot_id     VARCHAR(64)  NOT NULL REFERENCES st_snapshot(id) ON DELETE CASCADE,
    path            VARCHAR(512) NOT NULL,
    sha256          VARCHAR(64)  NOT NULL,
    size            BIGINT       NOT NULL,
    derived_from    VARCHAR(520),
    PRIMARY KEY (snapshot_id, path)
);

-- Queryable copy of the place catalog (records / tags) of a snapshot.
CREATE TABLE IF NOT EXISTS st_catalog_record (
    snapshot_id     VARCHAR(64)  NOT NULL REFERENCES st_snapshot(id) ON DELETE CASCADE,
    id              VARCHAR(128) NOT NULL,
    lang            VARCHAR(8),
    kind            VARCHAR(32),
    city            VARCHAR(32),
    name            VARCHAR(256),
    payload         TEXT,
    PRIMARY KEY (snapshot_id, id)
);
CREATE INDEX IF NOT EXISTS st_catalog_lookup ON st_catalog_record(snapshot_id, lang, city, kind, name);
CREATE TABLE IF NOT EXISTS st_catalog_tag (
    snapshot_id     VARCHAR(64)  NOT NULL REFERENCES st_snapshot(id) ON DELETE CASCADE,
    record_id       VARCHAR(128) NOT NULL,
    tag             VARCHAR(128),
    value           TEXT
);
CREATE INDEX IF NOT EXISTS st_catalog_tag_lookup ON st_catalog_tag(snapshot_id, tag);

-- Migration 2: rejected catalog rows are kept apart from the queryable catalog.
CREATE TABLE IF NOT EXISTS st_catalog_quarantine (
    snapshot_id     VARCHAR(64)  NOT NULL REFERENCES st_snapshot(id) ON DELETE CASCADE,
    id              VARCHAR(128) NOT NULL,
    city            VARCHAR(32)  NOT NULL,
    kind            VARCHAR(32)  NOT NULL,
    name            VARCHAR(256),
    reasons         TEXT         NOT NULL,
    payload         TEXT         NOT NULL,
    PRIMARY KEY (snapshot_id, id)
);
CREATE INDEX IF NOT EXISTS st_catalog_quarantine_lookup ON st_catalog_quarantine(snapshot_id, city, kind);

-- Migration 3: source-backed discovery records retain their planning restrictions.
CREATE TABLE IF NOT EXISTS st_catalog_reference (
    snapshot_id     VARCHAR(64)  NOT NULL,
    id              VARCHAR(128) NOT NULL,
    city            VARCHAR(32)  NOT NULL,
    kind            VARCHAR(32)  NOT NULL,
    name            VARCHAR(256) NOT NULL,
    payload         TEXT         NOT NULL,
    PRIMARY KEY (snapshot_id, id),
    FOREIGN KEY (snapshot_id, id) REFERENCES st_catalog_quarantine(snapshot_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS st_catalog_reference_lookup ON st_catalog_reference(snapshot_id, city, kind, name);
CREATE OR REPLACE VIEW st_catalog_browse AS
    SELECT snapshot_id, id, city, kind, name, 'catalog' AS entry_scope, payload FROM st_catalog_record
    UNION ALL
    SELECT snapshot_id, id, city, kind, name, 'reference_only' AS entry_scope, payload FROM st_catalog_reference;
CREATE OR REPLACE VIEW st_catalog_pending AS
    SELECT q.* FROM st_catalog_quarantine q
    WHERE NOT EXISTS (SELECT 1 FROM st_catalog_reference r WHERE r.snapshot_id = q.snapshot_id AND r.id = q.id);

-- ============================================================ app releases (PC package + APK)
CREATE TABLE IF NOT EXISTS st_release (
    version         VARCHAR(32)  PRIMARY KEY,
    snapshot_ids    VARCHAR(256) NOT NULL,
    android_version_code INT,
    apk_sha256      VARCHAR(64),
    apk_size        BIGINT,
    server_url      VARCHAR(256),
    notes           TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ============================================================ per-account trip data
-- user_id NULL marks bundled examples that every signed-in account may read.
CREATE TABLE IF NOT EXISTS st_trip_request (
    request_id      VARCHAR(32)  PRIMARY KEY,
    user_id         BIGINT       REFERENCES st_user(id) ON DELETE CASCADE,
    revision        INT,
    start_city      VARCHAR(32),
    target_city     VARCHAR(32),
    days            INT,
    people          INT,
    raw_text        TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS st_trip_request_user ON st_trip_request(user_id, updated_at);

CREATE TABLE IF NOT EXISTS st_trip_job (
    job_id          VARCHAR(32)  PRIMARY KEY,
    user_id         BIGINT       REFERENCES st_user(id) ON DELETE CASCADE,
    request_id      VARCHAR(32),
    state           VARCHAR(32),
    title           VARCHAR(128),
    client          VARCHAR(16),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    synced_state    VARCHAR(32)
);
CREATE INDEX IF NOT EXISTS st_trip_job_user ON st_trip_job(user_id, created_at);

CREATE TABLE IF NOT EXISTS st_itinerary_edit (
    edit_id         VARCHAR(32)  PRIMARY KEY,
    user_id         BIGINT       NOT NULL REFERENCES st_user(id) ON DELETE CASCADE,
    job_id          VARCHAR(32)  NOT NULL,
    state           VARCHAR(32),
    adopted         BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    synced_state    VARCHAR(32)
);
CREATE INDEX IF NOT EXISTS st_itinerary_edit_job ON st_itinerary_edit(user_id, job_id);

-- Mirror of the planner's result folders, so the server's local result/ is only a cache.
-- scope: tripspec | manual | inputs | edits
CREATE TABLE IF NOT EXISTS st_object_file (
    scope           VARCHAR(16)  NOT NULL,
    object_id       VARCHAR(32)  NOT NULL,
    path            VARCHAR(512) NOT NULL,
    sha256          VARCHAR(64)  NOT NULL,
    size            BIGINT       NOT NULL,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, object_id, path)
);

CREATE TABLE IF NOT EXISTS st_feedback (
    id              VARCHAR(32)  PRIMARY KEY,
    user_id         BIGINT       REFERENCES st_user(id) ON DELETE SET NULL,
    job_id          VARCHAR(32),
    candidate_id    VARCHAR(32),
    revision_id     VARCHAR(32),
    decision        VARCHAR(16),
    text            VARCHAR(1000),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
