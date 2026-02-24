# CA Legislation Daily Email Service

## Overview
Daily email service that sends California legislative updates to recipients.
Each bill with activity gets its own email. Runs as a Google Cloud Run service
triggered by Zapier.

## Architecture
```
LegiScan API (CA legislation)
        ↓
Google Cloud Run Service
        ↓
Zapier (daily schedule → loop → send emails)
        ↓
Recipients
```

## GCP Details
- **Project:** tax-scraper-486217
- **Region:** us-central1

## LegiScan API
- **State:** CA (California)
- **API Key:** Set via `LEGISCAN_API_KEY` environment variable
- **Free tier:** 30,000 queries/month
- **Change detection:** Filter `getMasterListRaw` by `last_action_date`

## Endpoint
`GET /?days=1&format=email`

Returns email-ready JSON array. Each item contains bill metadata, formatted
email subject/body, and links to the full bill text on LegiScan.

## Key Commands
```bash
# Local development
functions-framework --target=ca_legislation_daily --port=8080 --debug

# Deploy to Cloud Run
gcloud run deploy ca-legislation-daily \
  --source . \
  --region us-central1 \
  --project tax-scraper-486217 \
  --set-env-vars LEGISCAN_API_KEY=<key>

# Test
curl "http://localhost:8080/?days=1&format=email"
```

## Owner
Josh Youngblood (josh@josh.tax)
GitHub: joshy081
