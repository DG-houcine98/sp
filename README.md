# Order Processing - Serverless AWS Project

A learning project built to practice the DevOps stack from a specific job posting end-to-end:
AWS (multi-account, CloudFormation IaC), Jenkins with declarative Groovy pipelines,
Python/boto3, Bash, Docker, and pipeline-level security/quality gates.

See [docs/architecture.md](docs/architecture.md) for the data flow, IAM design, and a list of
deliberate simplifications made for a learning-scale project.

## Prerequisites

- AWS account + AWS CLI v2, configured with credentials that can create IAM roles, Lambda,
  API Gateway, DynamoDB, SQS/SNS, EventBridge, OpenSearch, CloudFront, S3, and ECR.
- Docker Desktop (for both running Jenkins locally and building the `process_order` image).
- Python 3.12, `jq`, `zip`.
- (Optional, for the Jenkins pipeline's Lint/Security stages, already covered by
  `requirements-dev.txt` inside the Jenkins container) `cfn-lint`, `checkov`, `pip-audit`,
  `flake8`, `black`, `shellcheck`.

## 1. Local dev setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v          # all Lambda logic, mocked with moto - no AWS calls
cfn-lint cloudformation/*.yaml
checkov -d cloudformation/
```

## 2. First deploy - manual path (do this before touching Jenkins)

Deploying manually first lets you verify each stack independently, and understand what the
Jenkins pipeline is automating before it's automating it.

```bash
chmod +x scripts/*.sh

# 1. Package all 4 Lambdas (3 zips + 1 container image) and publish their
#    locations to SSM. Requires stacks 00-01 to already exist for their SSM
#    outputs, EXCEPT this is the very first deploy - so deploy 00 and 01
#    first, then package, then the rest:
./scripts/deploy_stack.sh dev 00-network-iam
./scripts/deploy_stack.sh dev 01-storage
./scripts/package_lambdas.sh dev

./scripts/deploy_stack.sh dev 02-messaging
./scripts/deploy_stack.sh dev 03-search        # ~10-15 min - OpenSearch domain creation
./scripts/deploy_stack.sh dev 04-compute-api
./scripts/deploy_stack.sh dev 05-frontend-cdn
./scripts/deploy_stack.sh dev 06-monitoring

./scripts/deploy_frontend.sh dev
```

Test it:

```bash
# Get the API endpoint from stack 04's outputs, then:
curl -X POST "<ApiEndpoint from the output above>" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "cust-1", "item": "widget", "quantity": 2}'

# Check overall health:
python3 scripts/stack_status.py dev
```

Then open the CloudFront domain (`/order-processing/dev/frontend/distribution-domain` in SSM,
or stack 05's output) in a browser to use the demo form.

## 3. Running it through Jenkins instead

```bash
docker compose -f jenkins/docker-compose.yml up -d --build
```

1. Open `http://localhost:8080`. Get the initial admin password:
   `docker exec order-processing-jenkins cat /var/jenkins_home/secrets/initialAdminPassword`
2. Install suggested plugins.
3. **Manage Jenkins > Credentials** - add an "AWS Credentials" entry with ID `aws-dev`
   (and `aws-staging`/`aws-prod` later, for those environments), using an IAM user/role scoped
   to what's listed in Prerequisites.
4. **Manage Jenkins > In-process Script Approval** - after the pipeline's first run, approve
   the `Jenkins.instance.computers` signature used by `selectAgent()` in the Jenkinsfile (a
   one-time sandbox approval; see the comment above that function for why).
5. Create a new Pipeline job pointing at this repo, using `jenkins/Jenkinsfile`.
6. Run it with `ENVIRONMENT = dev`.

## 4. Tearing down

OpenSearch and the NAT-less networking here still cost money while deployed - tear down
when you're done testing:

```bash
./scripts/cleanup_resources.sh dev
```

This empties the S3 buckets, disables + deletes the CloudFront distribution (blocks for
5-15 min - this is a real AWS constraint, not a slow script), and deletes all 7 stacks in
reverse dependency order.

## Project layout

```
cloudformation/   7 stacks (00-06, deployed/deleted in that numeric order) + per-env params/
lambdas/          4 function handlers + shared common/boto3_clients.py
tests/            pytest + moto, no real AWS calls
scripts/          deploy_stack.sh, package_lambdas.sh, cleanup_resources.sh, stack_status.py, deploy_frontend.sh
docker/           multi-stage Dockerfile for the process_order container-image Lambda
jenkins/          Jenkinsfile, Dockerfile + docker-compose.yml to run Jenkins locally
frontend/         minimal demo UI served via CloudFront
docs/             architecture.md
```
