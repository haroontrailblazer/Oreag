-- Review metadata only. No changes to queries, retrieval, caches or providers.
CREATE TABLE public.knowledge_gap_reviews (
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  question_key text NOT NULL CHECK (question_key ~ '^[0-9a-f]{64}$'),
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
  note text CHECK (char_length(note) <= 2000),
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  resolved_at timestamptz,
  resolved_through_id bigint,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, question_key),
  CHECK (
    (status = 'open' AND resolved_at IS NULL AND resolved_through_id IS NULL) OR
    (status = 'resolved' AND resolved_at IS NOT NULL AND resolved_through_id IS NOT NULL AND resolved_through_id > 0)
  )
);
ALTER TABLE public.knowledge_gap_reviews ENABLE ROW LEVEL SECURITY;
-- Writes go through the owner API's evidence/revision checks. Direct clients
-- can only read their own projects' review metadata.
CREATE POLICY knowledge_gap_reviews_owner_read ON public.knowledge_gap_reviews
  FOR SELECT TO authenticated USING (
    EXISTS (SELECT 1 FROM public.projects p
            WHERE p.id = project_id AND p.owner_id = auth.uid())
  );
