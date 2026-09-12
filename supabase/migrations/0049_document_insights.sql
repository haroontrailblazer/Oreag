-- NULL means source attribution was not recorded; [] is a measured query
-- with no document sources. Historical logs must not be backfilled as zero.
ALTER TABLE public.query_logs ADD COLUMN IF NOT EXISTS document_sources jsonb;

CREATE TABLE IF NOT EXISTS public.document_reviews (
  file_id uuid PRIMARY KEY REFERENCES public.files(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  content_signature text NOT NULL CHECK (content_signature ~ '^[0-9a-f]{64}$'),
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  reviewed_by uuid NOT NULL
);
CREATE INDEX IF NOT EXISTS document_reviews_project_idx ON public.document_reviews(project_id);
ALTER TABLE public.document_reviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_reviews_owner_read ON public.document_reviews;
CREATE POLICY document_reviews_owner_read ON public.document_reviews
  FOR SELECT TO authenticated USING (
    EXISTS (SELECT 1 FROM public.projects p
            WHERE p.id = project_id AND p.owner_id = auth.uid())
  );
-- Writes use the authenticated backend so content/version checks cannot be skipped.
