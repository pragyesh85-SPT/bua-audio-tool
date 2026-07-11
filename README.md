# 🎵 Bua Audio Tool

Streamlit app that downloads audio from YouTube (yt-dlp), trims it, applies
fade in/out, optionally overlays a second track (pydub + ffmpeg), and exports
an MP3.

This repo is set up to deploy on **Google Cloud Run**, protected by
**Firebase Authentication** (email/password), with optional archiving of
processed files to **Cloud Storage**.

> **Why Cloud Run and not Firebase Hosting?** Firebase Hosting only serves
> static files, and its Cloud Run rewrites do **not** support WebSockets,
> which Streamlit requires. So the app runs on Cloud Run directly (you can
> map a custom domain to it). Firebase Auth and Storage still work — they're
> part of the same Google Cloud project.

---

## 1. One-time setup

### Prerequisites (on your PC)

- [Google Cloud CLI (`gcloud`)](https://cloud.google.com/sdk/docs/install) installed and logged in: `gcloud auth login`
- A Firebase project at <https://console.firebase.google.com> (a Firebase project **is** a Google Cloud project)
- **Billing enabled** on the project (required for Cloud Run; there is a generous free tier and the app scales to zero when idle)

### Firebase Authentication

1. Firebase console → **Build → Authentication → Get started**
2. **Sign-in method** → enable **Email/Password**
3. **Users** tab → **Add user** → create an email + password for each person allowed to use the tool (sign-up from the app is disabled on purpose)
4. Firebase console → ⚙️ **Project settings → General** → copy the **Web API Key**

---

## 2. Deploy to Cloud Run

From the repo root on your PC:

```bash
gcloud config set project YOUR_PROJECT_ID

gcloud run deploy bua-audio-tool \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --timeout 600 \
  --set-env-vars FIREBASE_WEB_API_KEY=YOUR_WEB_API_KEY
```

- `--allow-unauthenticated` is correct here: the app enforces its **own**
  Firebase login screen; without this flag Cloud Run would demand Google IAM
  auth before the page even loads.
- Pick the region nearest to you (`asia-south1` = Mumbai; `us-central1`, `europe-west1`, ...).
- First deploy takes a few minutes (it builds the Docker image with Cloud Build). At the end it prints your app URL, e.g. `https://bua-audio-tool-xxxxx.a.run.app`.

Open the URL → you get the sign-in page → log in with a user you created in Firebase.

### Redeploying after changes

Just run the same `gcloud run deploy` command again.

---

## 3. Optional: YouTube cookies (recommended)

YouTube often blocks requests from Google Cloud IPs ("confirm you're not a
bot"). Providing cookies from a logged-in browser session helps a lot.

1. Export cookies in Netscape format with a browser extension like "Get cookies.txt LOCALLY" while logged in to YouTube.
2. Store them in Secret Manager and attach to the service:

```bash
gcloud services enable secretmanager.googleapis.com
gcloud secrets create youtube-cookies --data-file=cookies.txt

gcloud run services update bua-audio-tool \
  --region asia-south1 \
  --set-secrets YOUTUBE_COOKIES=youtube-cookies:latest
```

If deploy fails with a permissions error, grant the service account access:

```bash
gcloud secrets add-iam-policy-binding youtube-cookies \
  --member serviceAccount:$(gcloud run services describe bua-audio-tool --region asia-south1 --format 'value(spec.template.spec.serviceAccountName)') \
  --role roles/secretmanager.secretAccessor
```

> ⚠️ Even with cookies, YouTube may still intermittently block datacenter
> IPs — this is the least reliable part of any cloud deployment of yt-dlp,
> and cookies expire so refresh them when downloads start failing. Also note
> downloading YouTube audio is against YouTube's Terms of Service; keep this
> for personal use.

---

## 4. Optional: save outputs to Cloud Storage

Processed MP3s are always downloadable in the browser. To *also* keep a copy
in a bucket (per-user folders + 24h shareable link):

```bash
# Create the bucket (name must be globally unique)
gcloud storage buckets create gs://YOUR_PROJECT_ID-bua-audio --location asia-south1

# Let the service account write to it
SA=$(gcloud run services describe bua-audio-tool --region asia-south1 --format 'value(spec.template.spec.serviceAccountName)')
gcloud storage buckets add-iam-policy-binding gs://YOUR_PROJECT_ID-bua-audio \
  --member serviceAccount:$SA --role roles/storage.objectAdmin

# Needed so the app can generate signed download links
gcloud iam service-accounts add-iam-policy-binding $SA \
  --member serviceAccount:$SA --role roles/iam.serviceAccountTokenCreator

# Tell the app about the bucket
gcloud run services update bua-audio-tool \
  --region asia-south1 \
  --set-env-vars OUTPUT_BUCKET=YOUR_PROJECT_ID-bua-audio
```

Files land at `gs://<bucket>/outputs/<user-email>/<timestamp>_bua_audio.mp3`.

---

## 5. Optional: custom domain

Cloud Run → your service → **Custom domains** (or **Integrations → Domain
mapping**) in the Google Cloud console. Don't use Firebase Hosting rewrites
in front of this app — they break Streamlit's WebSocket connection.

---

## Running locally

```bash
pip install -r requirements.txt   # plus ffmpeg installed on your system
streamlit run app.py
```

Without `FIREBASE_WEB_API_KEY` set, the login screen is skipped (local dev
mode). To test auth locally:

```bash
FIREBASE_WEB_API_KEY=your_key streamlit run app.py
```

## Configuration reference

| Env var | Required | Purpose |
|---|---|---|
| `FIREBASE_WEB_API_KEY` | yes (in production) | Enables the Firebase email/password login gate |
| `YOUTUBE_COOKIES` | no | Netscape-format cookies to reduce YouTube bot-blocking |
| `OUTPUT_BUCKET` | no | Cloud Storage bucket name to archive processed MP3s |
