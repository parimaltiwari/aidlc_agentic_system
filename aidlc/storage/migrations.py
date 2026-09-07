"""Plain SQL schema migration for the Postgres history store."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
  id text PRIMARY KEY,
  org_id text NOT NULL,
  name text NOT NULL,
  repo_url text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
  id text PRIMARY KEY,
  project_id text NOT NULL REFERENCES projects(id),
  intent text NOT NULL,
  context jsonb NOT NULL,
  status text NOT NULL,
  phase text NOT NULL,
  requested_by text NOT NULL,
  parent_run_id text REFERENCES runs(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifact_versions (
  id bigserial PRIMARY KEY,
  run_id text NOT NULL REFERENCES runs(id),
  key text NOT NULL,
  version int NOT NULL,
  schema text NOT NULL,
  phase text NOT NULL,
  agent text NOT NULL,
  attempt int NOT NULL DEFAULT 1,
  body jsonb NOT NULL,
  blob_uri text,
  content_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, key, version)
);
CREATE INDEX IF NOT EXISTS artifact_versions_run_key_version_idx
  ON artifact_versions (run_id, key, version DESC);
CREATE INDEX IF NOT EXISTS artifact_versions_body_idx
  ON artifact_versions USING gin (body jsonb_path_ops);

CREATE TABLE IF NOT EXISTS agent_invocations (
  id bigserial PRIMARY KEY,
  run_id text NOT NULL REFERENCES runs(id),
  phase text NOT NULL,
  agent text NOT NULL,
  work_item_id text,
  attempt int NOT NULL,
  worker_id text NOT NULL,
  temporal_activity_id text,
  model text,
  input_keys text[] NOT NULL,
  output_key text,
  prompt_tokens int,
  completion_tokens int,
  cost_usd numeric(10,4),
  started_at timestamptz NOT NULL,
  duration_ms int NOT NULL,
  ok boolean NOT NULL,
  error text
);
CREATE INDEX IF NOT EXISTS agent_invocations_run_started_idx
  ON agent_invocations (run_id, started_at);

CREATE TABLE IF NOT EXISTS scorecards (
  id bigserial PRIMARY KEY,
  run_id text NOT NULL REFERENCES runs(id),
  phase text NOT NULL,
  attempt int NOT NULL,
  agent text NOT NULL,
  scores jsonb NOT NULL,
  overall numeric(4,3) NOT NULL,
  passed boolean NOT NULL,
  feedback text[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gate_decisions (
  id bigserial PRIMARY KEY,
  run_id text NOT NULL REFERENCES runs(id),
  phase text NOT NULL,
  attempt int NOT NULL,
  decision text NOT NULL,
  reason text NOT NULL,
  approved boolean,
  approved_by text,
  approved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS change_requests (
  id bigserial PRIMARY KEY,
  run_id text NOT NULL REFERENCES runs(id),
  cr_id text NOT NULL,
  source_phase text NOT NULL,
  target_phase text NOT NULL,
  reason text NOT NULL,
  details text[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS run_events (
  id bigserial PRIMARY KEY,
  run_id text NOT NULL REFERENCES runs(id),
  ts timestamptz NOT NULL DEFAULT now(),
  level text NOT NULL,
  message text NOT NULL
);

INSERT INTO projects (id, org_id, name)
VALUES ('default', 'default', 'Default project')
ON CONFLICT (id) DO NOTHING;
"""


def apply(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute(SCHEMA_SQL)
    conn.commit()
