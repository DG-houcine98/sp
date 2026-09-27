#!/usr/bin/env bash
#
# Deploys one CloudFormation stack for one environment.
#
# Usage: deploy_stack.sh <env> <stack-basename> [--force]
#   env            dev | staging | prod
#   stack-basename e.g. 04-compute-api (matches cloudformation/<name>.yaml)
#   --force        bypass the pFrozen check for this environment
#
# Parameters passed to CloudFormation come from two layers:
#   1. Static values from cloudformation/params/<env>.json (everything
#      except pFrozen, which this script consumes itself).
#   2. Dynamic values resolved from SSM Parameter Store, driven by
#      cloudformation/deps/<stack-basename>.deps if that file exists.
#      Stacks with no cross-stack dependencies (00, 01, 02) simply have no
#      .deps file and skip this layer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CFN_DIR="${PROJECT_ROOT}/cloudformation"

usage() {
  echo "Usage: $0 <dev|staging|prod> <stack-basename> [--force]" >&2
  exit 1
}

[[ $# -lt 2 ]] && usage

ENVIRONMENT="$1"
STACK_BASENAME="$2"
FORCE="false"
[[ "${3:-}" == "--force" ]] && FORCE="true"

if [[ ! "${ENVIRONMENT}" =~ ^(dev|staging|prod)$ ]]; then
  echo "ERROR: env must be dev, staging, or prod (got '${ENVIRONMENT}')" >&2
  exit 1
fi

TEMPLATE_FILE="${CFN_DIR}/${STACK_BASENAME}.yaml"
PARAMS_FILE="${CFN_DIR}/params/${ENVIRONMENT}.json"
DEPS_FILE="${CFN_DIR}/deps/${STACK_BASENAME}.deps"

[[ -f "${TEMPLATE_FILE}" ]] || { echo "ERROR: template not found: ${TEMPLATE_FILE}" >&2; exit 1; }
[[ -f "${PARAMS_FILE}" ]] || { echo "ERROR: params file not found: ${PARAMS_FILE}" >&2; exit 1; }

# ---- 1. Frozen-environment gate ----
IS_FROZEN="$(jq -r '.pFrozen // "false"' "${PARAMS_FILE}")"
if [[ "${IS_FROZEN}" == "true" && "${FORCE}" != "true" ]]; then
  echo "ERROR: environment '${ENVIRONMENT}' is frozen (pFrozen=true in ${PARAMS_FILE})." >&2
  echo "       Re-run with --force if this deploy is intentional." >&2
  exit 1
fi

# ---- 2. Build --parameter-overrides ----
PARAM_OVERRIDES=()

# Static layer: every key in the env's params file except pFrozen.
while IFS='=' read -r key value; do
  [[ -z "${key}" ]] && continue
  PARAM_OVERRIDES+=("${key}=${value}")
done < <(jq -r 'to_entries | map(select(.key != "pFrozen")) | .[] | "\(.key)=\(.value)"' "${PARAMS_FILE}")

# Dynamic layer: resolve each mapped SSM path for this stack, if a .deps file exists.
if [[ -f "${DEPS_FILE}" ]]; then
  while IFS='=' read -r param_name ssm_path_template; do
    [[ -z "${param_name}" || "${param_name}" == \#* ]] && continue
    ssm_path="${ssm_path_template//\{env\}/${ENVIRONMENT}}"
    echo "Resolving ${param_name} from SSM path ${ssm_path} ..."
    resolved_value="$(aws ssm get-parameter --name "${ssm_path}" --query 'Parameter.Value' --output text)"
    PARAM_OVERRIDES+=("${param_name}=${resolved_value}")
  done < "${DEPS_FILE}"
fi

# Force a fresh AWS::ApiGateway::Deployment on every deploy for stacks that
# declare pDeploymentTrigger (currently only 04-compute-api) - see the comment
# on that parameter for why this is necessary: without it, adding/editing a
# method silently doesn't take effect on the live stage.
if grep -q "pDeploymentTrigger:" "${TEMPLATE_FILE}"; then
  TRIGGER_VALUE="$(git -C "${PROJECT_ROOT}" rev-parse --short HEAD 2>/dev/null || date +%s)"
  PARAM_OVERRIDES+=("pDeploymentTrigger=${TRIGGER_VALUE}")
fi

STACK_NAME="order-processing-${ENVIRONMENT}-${STACK_BASENAME}"

run_deploy() {
  aws cloudformation deploy \
    --template-file "${TEMPLATE_FILE}" \
    --stack-name "${STACK_NAME}" \
    --parameter-overrides "${PARAM_OVERRIDES[@]}" \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset
}

# ---- 3. Deploy, with one automatic rollback-recovery retry ----
if ! run_deploy; then
  echo "Deploy failed for ${STACK_NAME}, checking stack status..."
  STACK_STATUS="$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "NOT_FOUND")"

  if [[ "${STACK_STATUS}" == "ROLLBACK_COMPLETE" ]]; then
    echo "Stack is stuck in ROLLBACK_COMPLETE - deleting and retrying once..."
    aws cloudformation delete-stack --stack-name "${STACK_NAME}"
    aws cloudformation wait stack-delete-complete --stack-name "${STACK_NAME}"
    run_deploy
  else
    echo "ERROR: deploy failed and stack status is '${STACK_STATUS}' (not auto-recoverable)." >&2
    exit 1
  fi
fi

# ---- 4. Print outputs ----
echo ""
echo "Stack ${STACK_NAME} deployed. Outputs:"
aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --query 'Stacks[0].Outputs' --output json \
  | jq -r '.[] | "  \(.OutputKey) = \(.OutputValue)"'
