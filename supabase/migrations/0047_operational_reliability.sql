ALTER TABLE public.evaluation_runs ADD COLUMN IF NOT EXISTS archived_at timestamptz, ADD COLUMN IF NOT EXISTS archived_payload bytea;
CREATE INDEX IF NOT EXISTS evaluation_runs_retained_idx ON public.evaluation_runs(project_id,created_at DESC) WHERE archived_at IS NULL;
CREATE TABLE IF NOT EXISTS public.idempotency_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
 api_key_id uuid NOT NULL REFERENCES public.api_keys(id) ON DELETE CASCADE,
 operation text NOT NULL, key_hash text NOT NULL, request_hash text NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','completed','uncertain')),
 response_encrypted text, status_code integer,
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 UNIQUE(api_key_id,operation,key_hash)
);
CREATE INDEX IF NOT EXISTS idempotency_requests_expiry_idx ON public.idempotency_requests(expires_at);
CREATE TABLE IF NOT EXISTS public.request_metrics (
 id bigserial PRIMARY KEY,
 owner_id uuid, project_id uuid REFERENCES public.projects(id) ON DELETE CASCADE,
 endpoint text NOT NULL, status_code integer NOT NULL, outcome text NOT NULL,
 latency_ms double precision NOT NULL, first_token_ms double precision,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS request_metrics_owner_time_idx ON public.request_metrics(owner_id,created_at DESC);
CREATE INDEX IF NOT EXISTS request_metrics_project_time_idx ON public.request_metrics(project_id,created_at DESC);
CREATE INDEX IF NOT EXISTS request_metrics_time_idx ON public.request_metrics(created_at);
CREATE TABLE IF NOT EXISTS public.worker_heartbeats (
 instance_id text PRIMARY KEY, last_seen_at timestamptz NOT NULL, workers jsonb NOT NULL,
 pool_used integer, pool_limit integer, dropped_metrics integer NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS public.operation_snapshots (
 owner_id uuid PRIMARY KEY, report jsonb NOT NULL, checked_at timestamptz NOT NULL
);
ALTER TABLE public.idempotency_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.request_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.worker_heartbeats ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.operation_snapshots ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.idempotency_requests, public.request_metrics, public.worker_heartbeats, public.operation_snapshots FROM anon, authenticated;
