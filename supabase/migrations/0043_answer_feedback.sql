-- One owner rating per query. Existing ownership RLS on query_logs applies.
-- Apply before deploying the backend that reads these columns.
ALTER TABLE public.query_logs
  ADD COLUMN IF NOT EXISTS feedback_rating text,
  ADD COLUMN IF NOT EXISTS feedback_note text,
  ADD COLUMN IF NOT EXISTS feedback_updated_at timestamptz;

DO $$ BEGIN
ALTER TABLE public.query_logs
  ADD CONSTRAINT query_logs_feedback_rating_check
    CHECK (feedback_rating IN ('helpful', 'not_helpful')),
  ADD CONSTRAINT query_logs_feedback_note_check
    CHECK (char_length(feedback_note) <= 1000),
  ADD CONSTRAINT query_logs_feedback_state_check
    CHECK ((feedback_rating IS NULL AND feedback_note IS NULL AND feedback_updated_at IS NULL)
      OR (feedback_rating IS NOT NULL AND feedback_updated_at IS NOT NULL));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS query_logs_feedback_project_id_idx
  ON public.query_logs (project_id, feedback_rating, id DESC)
  WHERE feedback_rating IS NOT NULL;
