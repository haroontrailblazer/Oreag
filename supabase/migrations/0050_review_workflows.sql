-- Additive workflow metadata. Existing measurements remain unmodified.
ALTER TABLE public.query_logs ADD COLUMN IF NOT EXISTS cache_details jsonb;
ALTER TABLE public.evaluation_runs ADD COLUMN IF NOT EXISTS trigger_reason text;
ALTER TABLE public.evaluation_runs ADD COLUMN IF NOT EXISTS gap_key text;
ALTER TABLE public.evaluation_runs ADD COLUMN IF NOT EXISTS gap_evidence_version text;
ALTER TABLE public.knowledge_gap_reviews ADD COLUMN IF NOT EXISTS verification_run_id uuid REFERENCES public.evaluation_runs(id) ON DELETE SET NULL;
ALTER TABLE public.evaluation_schedules ADD COLUMN IF NOT EXISTS on_changes boolean NOT NULL DEFAULT false;
ALTER TABLE public.evaluation_schedules ADD COLUMN IF NOT EXISTS observed_signature text;
ALTER TABLE public.evaluation_schedules ADD COLUMN IF NOT EXISTS pending_signature text;
ALTER TABLE public.evaluation_schedules ADD COLUMN IF NOT EXISTS change_due_at timestamptz;
ALTER TABLE public.evaluation_schedules ADD COLUMN IF NOT EXISTS watch_after timestamptz NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS public.saved_query_views (
  id uuid PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 60),
  kind text NOT NULL CHECK (kind IN ('queries', 'failures')),
  filters jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (owner_id, kind, name)
);
CREATE INDEX IF NOT EXISTS saved_query_views_owner_idx ON public.saved_query_views(owner_id);
ALTER TABLE public.saved_query_views ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS saved_query_views_owner_read ON public.saved_query_views;
CREATE POLICY saved_query_views_owner_read ON public.saved_query_views
  FOR SELECT TO authenticated USING (owner_id = auth.uid());

CREATE TABLE IF NOT EXISTS public.source_conflict_reviews (
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  conflict_key text NOT NULL CHECK (conflict_key ~ '^[0-9a-f]{64}$'),
  status text NOT NULL CHECK (status IN ('open', 'confirmed', 'dismissed')),
  note text CHECK (char_length(note) <= 2000),
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, conflict_key)
);
ALTER TABLE public.source_conflict_reviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS source_conflict_reviews_owner_read ON public.source_conflict_reviews;
CREATE POLICY source_conflict_reviews_owner_read ON public.source_conflict_reviews
  FOR SELECT TO authenticated USING (EXISTS (
    SELECT 1 FROM public.projects p WHERE p.id = project_id AND p.owner_id = auth.uid()
  ));
