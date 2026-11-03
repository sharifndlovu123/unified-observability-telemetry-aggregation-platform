# Scenario 3: background processing failure

**Run:** `make scenario N=3`

**What it does:** `celery_fail` (60%) in the `generate_report` task, raising `SimulatedTaskError`.

## Expected outcome (checked automatically)
- `portal_celery_tasks_total{outcome="failure"}` increases; alert `CeleryTaskFailures` goes pending.
- The worker logs ERRORs carrying a `trace.id`, and that trace contains spans from **both** `portal-django` and `portal-celery-worker`: the failure is linked back to the web request that queued the job.

## Where to look
- **Grafana** → Background Processing → *Task success ratio*, *Failures by task*.
- **Kibana** → *Portal: errors and criticals*, then *Portal: follow a trace*.

## Think about
The failure happens in a different process, minutes after the request returned 202. How would you ever connect them without trace propagation?
