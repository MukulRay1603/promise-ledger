# Deploying the dec2 build (staging first, then production)

Nothing here has been run. Ray decides when. Two steps: a **staging** service first, so testers get a link without
touching the live site; then **production** once testing looks good.

Project: `promise-ledger-cloud`, region `us-central1`. Replace `PROD_BUCKET` with the bucket the live service uses
(`gcloud run services describe promise-ledger --region us-central1 --format='value(spec.template.spec.containers[0].env)'`).

## 0. Get the code

```bash
git clone https://github.com/MukulRay1603/promise-ledger.git && cd promise-ledger
git checkout dec2
```

## 1. Staging (separate data, so tests never touch the live site)

```bash
gcloud firestore databases create --database=staging --location=us-central1
gcloud storage buckets create gs://promise-ledger-staging-$(gcloud config get-value project) --location=us-central1
openssl rand -hex 24 | gcloud secrets create feedback-token --data-file=-
gcloud run deploy promise-ledger-staging --source . --region us-central1 --allow-unauthenticated \
  --no-cpu-throttling --cpu-boost --max-instances 2 \
  --set-env-vars STORAGE=gcp,GCS_BUCKET=promise-ledger-staging-$(gcloud config get-value project),FIRESTORE_DATABASE=staging \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest,FEEDBACK_TOKEN=feedback-token:latest
```

The service account needs read access to the new `feedback-token` secret, like `gemini-api-key`. On first start the
service seeds the sample deals and the 21 county deals; the county PDFs are downloaded from the County's site and
checked by hash, so the first minute or two after a deploy is slower.

Send testers: `https://<staging-url>/#/test`. Read their answers:

```bash
curl -H "X-Feedback-Token: $(gcloud secrets versions access latest --secret feedback-token)" https://<staging-url>/api/feedback
```

## 2. Production (after testing)

Same build, live data, and one warm instance for the judging window so the first visit is fast:

```bash
gcloud run deploy promise-ledger --source . --region us-central1 --allow-unauthenticated \
  --no-cpu-throttling --cpu-boost --min-instances 1 --max-instances 3 \
  --set-env-vars STORAGE=gcp,GCS_BUCKET=PROD_BUCKET,PUBLIC_BASE_URL=https://promise-ledger.web.app \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest,FEEDBACK_TOKEN=feedback-token:latest
```

**Cost note.** `--min-instances 1` with CPU always allocated keeps one instance running all month. Check the current
Cloud Run price for 1 vCPU and 512 MiB always on before leaving it on; set `--min-instances 0` again after judging.

**Rollback.** `gcloud run services update-traffic promise-ledger --to-revisions=<previous-revision>=100 --region us-central1`
(list revisions with `gcloud run revisions list --service promise-ledger --region us-central1`).

## 3. After deploying

- Open `/#/county` and check 21 agreements are listed and read.
- Open `/api/health`.
- The `main` branch on GitHub still holds the Nov 9 submission. Merging `dec2` into `main` needs the earlier revert
  undone first (`git revert 6a09065`), then the merge. Ray's call.
