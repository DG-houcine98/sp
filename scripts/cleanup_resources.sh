#!/usr/bin/env bash
#
# Tears down one environment's entire deployment: empties versioned S3
# buckets, disables + deletes the CloudFront distribution, then deletes all
# 7 stacks in reverse dependency order.
#
# This is the "automate resource cleanup" piece of the project - none of
# these steps are optional shortcuts, they're the actual reasons stack
# deletion fails if you just run `aws cloudformation delete-stack` directly:
#   - a versioned S3 bucket with objects/versions still in it -> DELETE_FAILED
#   - a CloudFront distribution that's still Enabled -> can't be deleted at all
#
# Usage: cleanup_resources.sh <env>
set -euo pipefail

PROJECT_NAME="order-processing"

[[ $# -lt 1 ]] && { echo "Usage: $0 <dev|staging|prod>" >&2; exit 1; }
ENVIRONMENT="$1"
[[ "${ENVIRONMENT}" =~ ^(dev|staging|prod)$ ]] || { echo "ERROR: env must be dev, staging, or prod" >&2; exit 1; }

ssm_get() {
  aws ssm get-parameter --name "$1" --query 'Parameter.Value' --output text 2>/dev/null || echo ""
}

read -r -p "This will permanently delete ALL '${ENVIRONMENT}' resources for ${PROJECT_NAME}. Type the environment name to confirm: " CONFIRM
[[ "${CONFIRM}" == "${ENVIRONMENT}" ]] || { echo "Aborted."; exit 1; }

# ---- 1. Empty versioned S3 buckets (must happen before stack 01 can delete them) ----
empty_bucket() {
  local bucket_name="$1"
  [[ -z "${bucket_name}" ]] && return 0
  echo "Emptying s3://${bucket_name} ..."

  # Paginates through all object versions + delete markers, batch-deleting
  # up to 1000 at a time (the API limit) until nothing is left.
  while true; do
    local objects
    objects="$(aws s3api list-object-versions \
      --bucket "${bucket_name}" \
      --output json \
      --query '{Objects: [Versions[].{Key:Key,VersionId:VersionId}, DeleteMarkers[].{Key:Key,VersionId:VersionId}][0][0:1000]}')"

    local count
    count="$(echo "${objects}" | jq '.Objects | length')"
    [[ "${count}" -eq 0 ]] && break

    aws s3api delete-objects --bucket "${bucket_name}" --delete "${objects}" >/dev/null
  done
  echo "  -> emptied"
}

ARTIFACTS_BUCKET="$(ssm_get "/${PROJECT_NAME}/${ENVIRONMENT}/storage/artifacts-bucket-name")"
FRONTEND_BUCKET="$(ssm_get "/${PROJECT_NAME}/${ENVIRONMENT}/storage/frontend-bucket-name")"
empty_bucket "${ARTIFACTS_BUCKET}"
empty_bucket "${FRONTEND_BUCKET}"

# ---- 2. Disable + delete the CloudFront distribution (blocks until fully done) ----
DISTRIBUTION_ID="$(ssm_get "/${PROJECT_NAME}/${ENVIRONMENT}/frontend/distribution-id")"
if [[ -n "${DISTRIBUTION_ID}" ]]; then
  echo "Disabling CloudFront distribution ${DISTRIBUTION_ID} ..."
  CONFIG_JSON="$(mktemp)"
  aws cloudfront get-distribution-config --id "${DISTRIBUTION_ID}" > "${CONFIG_JSON}"

  ETAG="$(jq -r '.ETag' "${CONFIG_JSON}")"
  jq '.DistributionConfig | .Enabled = false' "${CONFIG_JSON}" > "${CONFIG_JSON}.updated"

  aws cloudfront update-distribution \
    --id "${DISTRIBUTION_ID}" \
    --if-match "${ETAG}" \
    --distribution-config "file://${CONFIG_JSON}.updated" >/dev/null

  echo "Waiting for distribution to finish disabling (this can take 5-15 minutes) ..."
  aws cloudfront wait distribution-deployed --id "${DISTRIBUTION_ID}"

  NEW_ETAG="$(aws cloudfront get-distribution-config --id "${DISTRIBUTION_ID}" --query 'ETag' --output text)"
  echo "Deleting distribution ${DISTRIBUTION_ID} ..."
  aws cloudfront delete-distribution --id "${DISTRIBUTION_ID}" --if-match "${NEW_ETAG}"
  rm -f "${CONFIG_JSON}" "${CONFIG_JSON}.updated"
else
  echo "No CloudFront distribution found in SSM - skipping."
fi

# ---- 3. Delete all stacks in reverse dependency order ----
STACKS_IN_REVERSE=(06-monitoring 05-frontend-cdn 04-compute-api 03-search 02-messaging 01-storage 00-network-iam)

for stack_basename in "${STACKS_IN_REVERSE[@]}"; do
  stack_name="${PROJECT_NAME}-${ENVIRONMENT}-${stack_basename}"
  if aws cloudformation describe-stacks --stack-name "${stack_name}" >/dev/null 2>&1; then
    echo "Deleting stack ${stack_name} ..."
    aws cloudformation delete-stack --stack-name "${stack_name}"
    aws cloudformation wait stack-delete-complete --stack-name "${stack_name}"
    echo "  -> deleted"
  else
    echo "Stack ${stack_name} does not exist - skipping."
  fi
done

echo ""
echo "Cleanup complete for environment '${ENVIRONMENT}'."
