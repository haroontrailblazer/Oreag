-- Isolated, resumable evaluations. Never replace the live project's vectors.
CREATE TABLE public.evaluation_suites (
  project_id uuid PRIMARY KEY REFERENCES public.projects(id) ON DELETE CASCADE,
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  suite jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.evaluation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'preparing' CHECK (status IN ('preparing','running','completed','cancelled','failed')),
  suite jsonb NOT NULL,
  corpus jsonb NOT NULL,
  corpus_count integer NOT NULL CHECK (corpus_count BETWEEN 1 AND 2000),
  content_version bigint NOT NULL,
  prepared integer NOT NULL DEFAULT 0 CHECK (prepared >= 0),
  results jsonb NOT NULL DEFAULT '[]',
  error text,
  lease_token uuid,
  lease_until timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX evaluation_runs_project_created_idx ON public.evaluation_runs(project_id, created_at DESC);
CREATE TABLE public.evaluation_vectors (
  run_id uuid NOT NULL REFERENCES public.evaluation_runs(id) ON DELETE CASCADE,
  variant integer NOT NULL CHECK (variant BETWEEN 0 AND 1),
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  filename text NOT NULL,
  page_number integer,
  content text NOT NULL,
  is_memory boolean NOT NULL DEFAULT false,
  embedding vector NOT NULL,
  PRIMARY KEY (run_id, variant, ordinal)
);
-- Backend-only writes: RLS grants owners reads, not direct index/run mutation.
ALTER TABLE public.evaluation_suites ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evaluation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evaluation_vectors ENABLE ROW LEVEL SECURITY;
CREATE POLICY evaluation_suites_owner_read ON public.evaluation_suites FOR SELECT TO authenticated
 USING (EXISTS (SELECT 1 FROM public.projects p WHERE p.id = project_id AND p.owner_id = auth.uid()));
CREATE POLICY evaluation_runs_owner_read ON public.evaluation_runs FOR SELECT TO authenticated
 USING (EXISTS (SELECT 1 FROM public.projects p WHERE p.id = project_id AND p.owner_id = auth.uid()));
CREATE POLICY evaluation_vectors_owner_read ON public.evaluation_vectors FOR SELECT TO authenticated
 USING (EXISTS (SELECT 1 FROM public.evaluation_runs r JOIN public.projects p ON p.id = r.project_id WHERE r.id = run_id AND p.owner_id = auth.uid()));
