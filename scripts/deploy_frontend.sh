#!/usr/bin/env bash
#
# Syncs frontend/index.html to the frontend S3 bucket, with the
# __API_ENDPOINT__ placeholder substituted for the real API Gateway URL, and
# invalidates the CloudFront cache so the new version is actually served
# (without this, CloudFront keeps serving the previous version until its
# cache TTL expires).
#
# Not a CloudFormation deploy - this is a plain content-sync step, run after
# stacks 01, 04, and 05 are all already deployed (it needs all three).
#
# Usage: deploy_frontend.sh <env>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_NAME="order-processing"

[[ $# -lt 1 ]] && { echo "Usage: $0 <dev|staging|prod>" >&2; exit 1; }
ENVIRONMENT="$1"
[[ "${ENVIRONMENT}" =~ ^(dev|staging|prod)$ ]] || { echo "ERROR: env must be dev, staging, or prod" >&2; exit 1; }

ssm_get() {
  aws ssm get-parameter --name "$1" --query 'Parameter.Value' --output text
}

FRONTEND_BUCKET="$(ssm_get "/${PROJECT_NAME}/${ENVIRONMENT}/storage/frontend-bucket-name")"
DISTRIBUTION_ID="$(ssm_get "/${PROJECT_NAME}/${ENVIRONMENT}/frontend/distribution-id")"
API_ENDPOINT="$(aws cloudformation describe-stacks \
  --stack-name "${PROJECT_NAME}-${ENVIRONMENT}-04-compute-api" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" --output text)"

echo "Substituting API endpoint (${API_ENDPOINT}) into index.html ..."
BUILD_FILE="$(mktemp)"
sed "s|__API_ENDPOINT__|${API_ENDPOINT}|g" "${PROJECT_ROOT}/frontend/index.html" > "${BUILD_FILE}"

echo "Uploading to s3://${FRONTEND_BUCKET}/index.html ..."
aws s3 cp "${BUILD_FILE}" "s3://${FRONTEND_BUCKET}/index.html" --content-type "text/html"
rm -f "${BUILD_FILE}"

echo "Invalidating CloudFront cache for distribution ${DISTRIBUTION_ID} ..."
aws cloudfront create-invalidation --distribution-id "${DISTRIBUTION_ID}" --paths "/index.html" >/dev/null

DOMAIN="$(ssm_get "/${PROJECT_NAME}/${ENVIRONMENT}/frontend/distribution-domain")"
echo ""
echo "Frontend deployed: https://${DOMAIN}/index.html"
