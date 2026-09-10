-- Warning-only budgets. No triggers or changes to the live request pipeline.
CREATE TABLE public.usage_budgets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  project_id uuid REFERENCES public.projects(id) ON DELETE CASCADE,
  scope_key text NOT NULL,
  amount_usd numeric(18,2) NOT NULL CHECK (amount_usd > 0 AND amount_usd <= 1000000),
  warning_percent integer NOT NULL DEFAULT 80 CHECK (warning_percent BETWEEN 1 AND 99),
  enabled boolean NOT NULL DEFAULT true,
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  last_checked_at timestamptz,
  next_check_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(owner_id, scope_key),
  CHECK ((project_id IS NULL AND scope_key = 'account') OR (project_id IS NOT NULL AND scope_key = project_id::text))
);
CREATE INDEX usage_budgets_due_idx ON public.usage_budgets(next_check_at) WHERE enabled;
CREATE TABLE public.usage_budget_alerts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  budget_id uuid NOT NULL REFERENCES public.usage_budgets(id) ON DELETE CASCADE,
  period_start date NOT NULL,
  threshold_percent integer NOT NULL CHECK (threshold_percent BETWEEN 1 AND 100),
  amount_usd numeric(18,2) NOT NULL,
  spent_usd numeric(24,10) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  read_at timestamptz,
  UNIQUE(budget_id, period_start, threshold_percent)
);
CREATE INDEX usage_budget_alerts_budget_created_idx ON public.usage_budget_alerts(budget_id, created_at DESC);
CREATE INDEX IF NOT EXISTS usage_events_owner_created_budget_idx ON public.usage_events(owner_id, created_at);
CREATE INDEX IF NOT EXISTS usage_events_owner_project_created_budget_idx ON public.usage_events(owner_id, project_id, created_at);
ALTER TABLE public.usage_budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usage_budget_alerts ENABLE ROW LEVEL SECURITY;
CREATE POLICY usage_budgets_owner_read ON public.usage_budgets FOR SELECT TO authenticated USING (owner_id = auth.uid());
CREATE POLICY usage_budget_alerts_owner_read ON public.usage_budget_alerts FOR SELECT TO authenticated
 USING (EXISTS (SELECT 1 FROM public.usage_budgets b WHERE b.id = budget_id AND b.owner_id = auth.uid()));
