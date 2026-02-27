#!/bin/bash
# =============================================================================
# deploy.sh — Deploy sdlc-assist-mcp to Google Cloud Run
#
# This script walks through each step. You can also run the commands
# manually one at a time if you prefer.
# =============================================================================

set -e  # Exit on any error

# ---------------------------------------------------------------------------
# CONFIGURATION — Update these values for your environment
# ---------------------------------------------------------------------------
PROJECT_ID="sdlc-assist"       # <-- CHANGE THIS to your GCP project ID
REGION="us-central1"                     # Match your Vertex AI agents region
SERVICE_NAME="sdlc-assist-mcp"
REPO_NAME="sdlc-assist"                 # Artifact Registry repo name

# Supabase credentials (these get set as Cloud Run secrets)
# You'll be prompted to enter these during deployment
# DO NOT hardcode them here

# ---------------------------------------------------------------------------
# STEP 1: Make sure you're authenticated and on the right project
# ---------------------------------------------------------------------------
echo "============================================"
echo "Step 1: Setting GCP project to ${PROJECT_ID}"
echo "============================================"
gcloud config set project ${PROJECT_ID}
gcloud auth list  # Shows your authenticated accounts

# ---------------------------------------------------------------------------
# STEP 2: Enable the required APIs (only needed once per project)
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Step 2: Enabling required APIs"
echo "============================================"
gcloud services enable \
    run.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    secretmanager.googleapis.com

echo "APIs enabled."

# ---------------------------------------------------------------------------
# STEP 3: Create Artifact Registry repository (only needed once)
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Step 3: Creating Artifact Registry repository"
echo "============================================"
gcloud artifacts repositories create ${REPO_NAME} \
    --repository-format=docker \
    --location=${REGION} \
    --description="SDLC Assist container images" \
    2>/dev/null || echo "Repository already exists, skipping."

# ---------------------------------------------------------------------------
# STEP 4: Store Supabase credentials in Secret Manager
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Step 4: Storing secrets in Secret Manager"
echo "============================================"
echo "You'll be prompted to enter your Supabase credentials."
echo ""

# Check if secrets already exist, create if not
if ! gcloud secrets describe supabase-url --project=${PROJECT_ID} 2>/dev/null; then
    echo "Enter your SUPABASE_URL (e.g., https://mtzcookrjzewywyirhja.supabase.co):"
    read -r SUPABASE_URL_VALUE
    echo -n "${SUPABASE_URL_VALUE}" | gcloud secrets create supabase-url --data-file=-
    echo "✅ supabase-url secret created"
else
    echo "✅ supabase-url secret already exists"
fi

if ! gcloud secrets describe supabase-service-role-key --project=${PROJECT_ID} 2>/dev/null; then
    echo "Enter your SUPABASE_SERVICE_ROLE_KEY:"
    read -rs SUPABASE_KEY_VALUE
    echo ""
    echo -n "${SUPABASE_KEY_VALUE}" | gcloud secrets create supabase-service-role-key --data-file=-
    echo "✅ supabase-service-role-key secret created"
else
    echo "✅ supabase-service-role-key secret already exists"
fi

# ---------------------------------------------------------------------------
# STEP 5: Build and push the container image
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Step 5: Building container image with Cloud Build"
echo "============================================"
echo "This builds the Docker image in the cloud (no Docker needed locally)."
echo ""

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest"

gcloud builds submit \
    --tag ${IMAGE_URI} \
    --region=${REGION}

echo "✅ Image built: ${IMAGE_URI}"

# ---------------------------------------------------------------------------
# STEP 6: Deploy to Cloud Run
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Step 6: Deploying to Cloud Run"
echo "============================================"

# Get the default compute service account for secret access
PROJECT_NUMBER=$(gcloud projects describe ${PROJECT_ID} --format='value(projectNumber)')
SA_EMAIL="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Grant the service account access to the secrets
gcloud secrets add-iam-policy-binding supabase-url \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet

gcloud secrets add-iam-policy-binding supabase-service-role-key \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet

# Deploy the service
gcloud run deploy ${SERVICE_NAME} \
    --image=${IMAGE_URI} \
    --region=${REGION} \
    --platform=managed \
    --no-allow-unauthenticated \
    --set-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_ROLE_KEY=supabase-service-role-key:latest" \
    --port=8080 \
    --memory=512Mi \
    --min-instances=0 \
    --max-instances=3 \
    --timeout=60

# ---------------------------------------------------------------------------
# STEP 7: Get the service URL
# ---------------------------------------------------------------------------
echo ""
echo "============================================"
echo "Step 7: Deployment complete!"
echo "============================================"

SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format='value(status.url)')

echo ""
echo "🚀 Your MCP server is live at:"
echo "   ${SERVICE_URL}"
echo ""
echo "The MCP endpoint is:"
echo "   ${SERVICE_URL}/mcp"
echo ""
echo "The service requires authentication (--no-allow-unauthenticated)."
echo "Your Spring Boot backend will need to include an auth token when calling it."
echo ""
echo "To test locally with the proxy:"
echo "   gcloud run services proxy ${SERVICE_NAME} --region=${REGION}"
echo "   Then connect to: http://localhost:8080/mcp"
