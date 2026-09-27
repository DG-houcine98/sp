#!/usr/bin/env bash
#
# Packages all 4 Lambda functions and publishes their locations to SSM, so
# scripts/deploy_stack.sh dev 04-compute-api (via its .deps file) can resolve
# them without this script and the CFN stack needing to talk to each other
# any other way.
#
# - create_order, index_to_opensearch, cleanup_stale_orders: zipped, uploaded
#   to the artifacts S3 bucket (created in 01-storage.yaml).
# - process_order: built as a container image (docker/Dockerfile.lambda),
#   pushed to the ECR repository already created by 01-storage.yaml (this
#   script only reads its URI - it never creates AWS infrastructure itself).
#
# Usage: package_lambdas.sh <env>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAMBDAS_DIR="${PROJECT_ROOT}/lambdas"

[[ $# -lt 1 ]] && { echo "Usage: $0 <dev|staging|prod>" >&2; exit 1; }
ENVIRONMENT="$1"
[[ "${ENVIRONMENT}" =~ ^(dev|staging|prod)$ ]] || { echo "ERROR: env must be dev, staging, or prod" >&2; exit 1; }

PROJECT_NAME="order-processing"
GIT_SHA="$(git -C "${PROJECT_ROOT}" rev-parse --short HEAD 2>/dev/null || echo "local")"

ssm_get() {
  aws ssm get-parameter --name "$1" --query 'Parameter.Value' --output text
}

ssm_put() {
  aws ssm put-parameter --name "$1" --value "$2" --type String --overwrite >/dev/null
}

ARTIFACTS_BUCKET="$(ssm_get "/${PROJECT_NAME}/${ENVIRONMENT}/storage/artifacts-bucket-name")"

# ---- zip-based functions ----
package_zip_function() {
  local function_dir="$1"     # e.g. create_order
  local ssm_key_path="$2"     # e.g. /order-processing/dev/artifacts/create-order-code-key

  echo "Packaging ${function_dir} ..."
  local build_dir
  build_dir="$(mktemp -d)"
  trap 'rm -rf "${build_dir}"' RETURN

  cp "${LAMBDAS_DIR}/${function_dir}/handler.py" "${build_dir}/"
  cp -r "${LAMBDAS_DIR}/common" "${build_dir}/common"

  local requirements_file="${LAMBDAS_DIR}/${function_dir}/requirements.txt"
  if [[ -s "${requirements_file}" ]] && grep -qv '^\s*#' "${requirements_file}"; then
    pip install -q -r "${requirements_file}" -t "${build_dir}" --upgrade
  fi

  local zip_path="${build_dir}.zip"
  (cd "${build_dir}" && zip -qr "${zip_path}" .)

  local s3_key="lambdas/${function_dir}/${GIT_SHA}.zip"
  aws s3 cp "${zip_path}" "s3://${ARTIFACTS_BUCKET}/${s3_key}" --quiet
  rm -f "${zip_path}"

  ssm_put "${ssm_key_path}" "${s3_key}"
  echo "  -> s3://${ARTIFACTS_BUCKET}/${s3_key}"
}

package_zip_function "create_order" "/${PROJECT_NAME}/${ENVIRONMENT}/artifacts/create-order-code-key"
package_zip_function "index_to_opensearch" "/${PROJECT_NAME}/${ENVIRONMENT}/artifacts/index-opensearch-code-key"
package_zip_function "cleanup_stale_orders" "/${PROJECT_NAME}/${ENVIRONMENT}/artifacts/cleanup-orders-code-key"

# ---- process_order: container image ----
echo "Building process_order container image ..."
REPOSITORY_URI="$(ssm_get "/${PROJECT_NAME}/${ENVIRONMENT}/storage/process-order-repository-uri")"
IMAGE_TAG="${GIT_SHA}"
IMAGE_URI="${REPOSITORY_URI}:${IMAGE_TAG}"

AWS_REGION="${AWS_DEFAULT_REGION:-$(aws configure get region)}"
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${REPOSITORY_URI%%/*}"

# Separate login for the public ECR gallery (public.ecr.aws), which the Dockerfile
# pulls its base image from. This is a different registry from the private ECR
# above, and its auth API is only served from us-east-1 regardless of deploy region.
# Without this, docker build pulls anonymously and hits public ECR's low anonymous
# rate limit, which surfaces as a 403 Forbidden on the base image pull.
aws ecr-public get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin public.ecr.aws

docker build \
  --provenance=false --sbom=false \
  -f "${PROJECT_ROOT}/docker/Dockerfile.lambda" \
  -t "${IMAGE_URI}" \
  "${PROJECT_ROOT}"

docker push "${IMAGE_URI}"

ssm_put "/${PROJECT_NAME}/${ENVIRONMENT}/artifacts/process-order-image-uri" "${IMAGE_URI}"
echo "  -> ${IMAGE_URI}"

echo ""
echo "All Lambda artifacts packaged for ${ENVIRONMENT} (git sha: ${GIT_SHA})."
