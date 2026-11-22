# Running Promise Ledger in production

Project `promise-ledger-cloud`, region `us-central1`. Services: `promise-ledger-staging` (test) and `promise-ledger` (live).

## Promote staging to production, and roll back

Deploy the exact image that passed on staging, not a rebuild:

```bash
IMG=$(gcloud run services describe promise-ledger-staging --region us-central1 --format='value(spec.template.spec.containers[0].image)')
DIGEST=$(gcloud artifacts docker images describe "$IMG" --format='value(image_summary.fully_qualified_digest)')
gcloud run deploy promise-ledger --region us-central1 --image "$DIGEST"   # keeps the service's settings and secrets
```

Roll back in one command, to the revision before:

```bash
gcloud run revisions list --service promise-ledger --region us-central1 --limit 3
gcloud run services update-traffic promise-ledger --region us-central1 --to-revisions PREVIOUS_REVISION=100
```

Git rollback point: tag `v1.0-stable`.

## Settings worth setting on production

| Setting | Value | Why |
|---|---|---|
| `MEDIA_BASE_URL` | `https://storage.googleapis.com/promise-ledger-media-1071927289312/` | The 8 explainer videos |
| `DAILY_AI_BUDGET_USD` | `2` (default) | Ceiling on what chat answers spend per server per day; past it, answers come from code and quotes |
| `RATE_LIMIT_COUNTY_ASKS_PER_HOUR` | `30` (default) | Chat questions per network per hour |
| `--min-instances` | `1` during judging | No cold start for the first visitor (about $5–10 a month); back to `0` after |

```bash
gcloud run services update promise-ledger --region us-central1 --min-instances 1 \
  --update-env-vars DAILY_AI_BUDGET_USD=2
```

## Alerts

- **Budget:** in Billing → Budgets & alerts, add a budget on the project (for example $10 a month) with email alerts at 50%, 90% and 100%. Also cap the Gemini key's quota in AI Studio.
- **Uptime:** in Monitoring → Uptime checks, check `https://<service>/api/health` every 5 minutes and email on failure. `/api/health?deep=1` gives the self-healing report: storage, stuck readings, county data, search index, the model breaker, and AI spend today.
- **Errors:** Error Reporting picks up Cloud Run exceptions by itself. Turn on its email notifications.

## County records

Deploys load the county records from saved readings and never call the model. If the county's records system changes a PDF, the deployed copy is kept. To check every record against the source and bundle any that changed, run `python tools/county_bundle.py` (`--dry-run` only reports), then commit and deploy.

## Already in place

- Security headers: Content Security Policy, HSTS, `nosniff`, no framing.
- Static files are revalidated by ETag (fast 304 responses).
- Self-healing watchdog: `app/healing.py`.
