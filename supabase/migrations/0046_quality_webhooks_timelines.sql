-- Additive jobs/outbox schema. No live retrieval or project configuration changes.
ALTER TABLE public.evaluation_runs
 ADD COLUMN execution text NOT NULL DEFAULT 'manual' CHECK (execution IN ('manual','background')),
 ADD COLUMN requested_by_key_id uuid,
 ADD COLUMN reference_run_id uuid REFERENCES public.evaluation_runs(id) ON DELETE SET NULL,
 ADD COLUMN quality_limits jsonb,
 ADD COLUMN quality_report jsonb;
CREATE INDEX evaluation_runs_work_idx ON public.evaluation_runs(updated_at) WHERE execution = 'background' AND status IN ('preparing','running');
CREATE INDEX evaluation_runs_assess_idx ON public.evaluation_runs(created_at) WHERE status = 'completed' AND quality_report IS NULL;
ALTER TABLE public.query_logs ADD COLUMN timeline jsonb;
CREATE TABLE public.evaluation_schedules (
 project_id uuid PRIMARY KEY REFERENCES public.projects(id) ON DELETE CASCADE,
 enabled boolean NOT NULL DEFAULT false,
 interval_hours integer NOT NULL DEFAULT 24 CHECK (interval_hours IN (6,12,24,168)),
 suite jsonb NOT NULL,
 reference_run_id uuid REFERENCES public.evaluation_runs(id) ON DELETE SET NULL,
 quality_limits jsonb NOT NULL,
 next_run_at timestamptz NOT NULL DEFAULT now(),
 last_run_at timestamptz,
 last_error text,
 revision integer NOT NULL DEFAULT 1 CHECK (revision > 0)
);
CREATE INDEX evaluation_schedules_due_idx ON public.evaluation_schedules(next_run_at) WHERE enabled;
CREATE TABLE public.webhook_endpoints (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
 url text NOT NULL,
 events jsonb NOT NULL,
 secret_encrypted text NOT NULL,
 enabled boolean NOT NULL DEFAULT true,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX webhook_endpoints_project_idx ON public.webhook_endpoints(project_id);
CREATE TABLE public.webhook_deliveries (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 endpoint_id uuid NOT NULL REFERENCES public.webhook_endpoints(id) ON DELETE CASCADE,
 event_id uuid NOT NULL,
 event_type text NOT NULL,
 payload jsonb NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','delivered','failed')),
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
 next_attempt_at timestamptz NOT NULL DEFAULT now(),
 lease_token uuid,
 lease_until timestamptz,
 response_status integer,
 last_error text,
 history jsonb NOT NULL DEFAULT '[]',
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(endpoint_id,event_id)
);
CREATE INDEX webhook_deliveries_due_idx ON public.webhook_deliveries(next_attempt_at) WHERE status = 'pending';
CREATE INDEX webhook_deliveries_history_idx ON public.webhook_deliveries(endpoint_id,created_at DESC);
ALTER TABLE public.evaluation_schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.webhook_endpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.webhook_deliveries ENABLE ROW LEVEL SECURITY;
CREATE POLICY evaluation_schedules_owner_read ON public.evaluation_schedules FOR SELECT TO authenticated
 USING (EXISTS (SELECT 1 FROM public.projects p WHERE p.id = project_id AND p.owner_id = auth.uid()));
-- Webhook secrets and delivery records are accessed only through the owner API.
REVOKE ALL ON public.webhook_endpoints, public.webhook_deliveries FROM anon, authenticated;

CREATE FUNCTION public.enqueue_webhook(pid uuid, kind text, event_data jsonb) RETURNS void
 LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE eid uuid := gen_random_uuid();
BEGIN
 INSERT INTO public.webhook_deliveries(endpoint_id,event_id,event_type,payload)
 SELECT e.id,eid,kind,jsonb_build_object('id',eid,'type',kind,'created_at',now(),'project_id',pid,'data',event_data)
 FROM public.webhook_endpoints e WHERE e.project_id = pid AND e.enabled AND e.events ? kind;
END $$;
REVOKE ALL ON FUNCTION public.enqueue_webhook(uuid,text,jsonb) FROM PUBLIC,anon,authenticated;

CREATE FUNCTION public.file_webhook_event() RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
 IF TG_OP = 'UPDATE' AND NEW.status IS NOT DISTINCT FROM OLD.status THEN RETURN NEW; END IF;
 IF NEW.status IN ('indexed','failed') THEN
  PERFORM public.enqueue_webhook(NEW.project_id, CASE WHEN NEW.status = 'indexed' THEN 'file.indexed' ELSE 'file.failed' END,
   jsonb_build_object('file_id',NEW.id,'status',NEW.status));
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER file_webhook_outbox AFTER INSERT OR UPDATE OF status ON public.files FOR EACH ROW EXECUTE FUNCTION public.file_webhook_event();

CREATE FUNCTION public.evaluation_webhook_event() RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
 IF NEW.status IN ('completed','failed') AND NEW.status IS DISTINCT FROM OLD.status THEN
  PERFORM public.enqueue_webhook(NEW.project_id, 'evaluation.' || NEW.status,jsonb_build_object('run_id',NEW.id,'status',NEW.status));
 END IF;
 IF NEW.quality_report->>'state' = 'regressed' AND OLD.quality_report IS DISTINCT FROM NEW.quality_report THEN
  PERFORM public.enqueue_webhook(NEW.project_id,'evaluation.regressed',jsonb_build_object('run_id',NEW.id,'quality_report',NEW.quality_report));
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER evaluation_webhook_outbox AFTER UPDATE OF status,quality_report ON public.evaluation_runs FOR EACH ROW EXECUTE FUNCTION public.evaluation_webhook_event();

CREATE FUNCTION public.budget_webhook_event() RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE pid uuid;
BEGIN
 SELECT project_id INTO pid FROM public.usage_budgets WHERE id = NEW.budget_id;
 -- Account spend must never be exposed through a project's integration.
 IF pid IS NOT NULL THEN
  PERFORM public.enqueue_webhook(pid,'budget.threshold_reached',jsonb_build_object('alert_id',NEW.id,'budget_id',NEW.budget_id,
   'period_start',NEW.period_start,'threshold_percent',NEW.threshold_percent,'amount_usd',NEW.amount_usd,'spent_usd',NEW.spent_usd));
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER budget_webhook_outbox AFTER INSERT ON public.usage_budget_alerts FOR EACH ROW EXECUTE FUNCTION public.budget_webhook_event();
REVOKE ALL ON FUNCTION public.file_webhook_event(), public.evaluation_webhook_event(), public.budget_webhook_event() FROM PUBLIC,anon,authenticated;
