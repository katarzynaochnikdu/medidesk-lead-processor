#!/bin/bash
# Skrypt do ręcznego deployu na Cloud Run
# Użycie: ./deploy.sh <project-id>

set -e

PROJECT_ID=${1:-$(gcloud config get-value project)}
REGION="europe-central2"
SERVICE_NAME="lead-processor"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/lead-processor/${SERVICE_NAME}"

echo "🚀 Deploying Lead Processor to Cloud Run"
echo "   Project: ${PROJECT_ID}"
echo "   Region: ${REGION}"
echo "   Service: ${SERVICE_NAME}"

# 1. Utwórz Artifact Registry repository (jeśli nie istnieje)
echo "📦 Creating Artifact Registry repository..."
gcloud artifacts repositories create lead-processor \
    --repository-format=docker \
    --location=${REGION} \
    --description="Lead Processor Docker images" \
    2>/dev/null || echo "   Repository already exists"

# 2. Skonfiguruj Docker auth
echo "🔐 Configuring Docker auth..."
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

# 3. Build obrazu
echo "🔨 Building Docker image..."
docker build -t ${IMAGE_NAME}:latest .

# 4. Push obrazu
echo "📤 Pushing image to Artifact Registry..."
docker push ${IMAGE_NAME}:latest

# 5. Deploy do Cloud Run
echo "☁️ Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_NAME}:latest \
    --region ${REGION} \
    --platform managed \
    --memory 512Mi \
    --cpu 1 \
    --min-instances 0 \
    --max-instances 10 \
    --timeout 300s \
    --allow-unauthenticated \
    --set-env-vars "ENVIRONMENT=production,GCP_REGION=${REGION},GCP_PROJECT_ID=${PROJECT_ID}" \
    --set-secrets "GUS_API_KEY=REGON_API_KEY_TOKEN:latest,API_KEY=GCP_API_KEY_ID:latest,ZOHO_CLIENT_ID=ZOHO_MD_CRM_LEADY_CRUD_CLIENT_ID:latest,ZOHO_CLIENT_SECRET=ZOHO_MD_CRM_LEADY_CRUD_CLIENT_SECRET:latest,ZOHO_REFRESH_TOKEN=ZOHO_MD_CRM_LEADY_CRUD_REFRESH_TOKEN:latest,BRAVE_SEARCH_API_KEY=BRAVE_SEARCH_API_KEY:latest"

# 6. Pobierz URL serwisu
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format 'value(status.url)')

echo ""
echo "✅ Deployment complete!"
echo "   Service URL: ${SERVICE_URL}"
echo ""
echo "📋 Next steps:"
echo "   1. Add secrets to Secret Manager:"
echo "      gcloud secrets create api-key --data-file=- <<< 'your-api-key'"
echo "      gcloud secrets create gus-api-key --data-file=- <<< 'your-gus-key'"
echo "      gcloud secrets create zoho-refresh-token --data-file=- <<< 'your-token'"
echo ""
echo "   2. Update Cloud Run with secrets:"
echo "      gcloud run services update ${SERVICE_NAME} --region ${REGION} \\"
echo "        --set-secrets=API_KEY=api-key:latest,GUS_API_KEY=gus-api-key:latest"
echo ""
echo "   3. Test the service:"
echo "      curl -X POST ${SERVICE_URL}/process \\"
echo "        -H 'Content-Type: application/json' \\"
echo "        -H 'X-API-Key: your-api-key' \\"
echo "        -d '{\"data\": {\"raw_name\": \"Jan Kowalski\"}}'"
