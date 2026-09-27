#!/usr/bin/env python3
"""
Prints the CloudFormation status of all 7 stacks for one environment.

Used both manually (`python3 stack_status.py dev`) and as a Jenkins
smoke-test stage after a deploy - exits non-zero if any stack is not in a
healthy *_COMPLETE state, so the pipeline can fail the build on it rather
than silently continuing.
"""
import sys

import boto3
from botocore.exceptions import ClientError

PROJECT_NAME = "order-processing"
STACK_BASENAMES = [
    "00-network-iam",
    "01-storage",
    "02-messaging",
    "03-search",
    "04-compute-api",
    "05-frontend-cdn",
    "06-monitoring",
]

HEALTHY_SUFFIXES = ("_COMPLETE",)
UNHEALTHY_STATUSES = {"ROLLBACK_COMPLETE", "UPDATE_ROLLBACK_FAILED", "DELETE_FAILED"}


def is_healthy(status):
    if status in UNHEALTHY_STATUSES:
        return False
    return status.endswith(HEALTHY_SUFFIXES)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("dev", "staging", "prod"):
        print("Usage: stack_status.py <dev|staging|prod>", file=sys.stderr)
        sys.exit(1)

    environment = sys.argv[1]
    client = boto3.client("cloudformation")

    print(f"{'STACK':<35} {'STATUS':<25} {'LAST UPDATED'}")
    print("-" * 90)

    all_healthy = True
    for basename in STACK_BASENAMES:
        stack_name = f"{PROJECT_NAME}-{environment}-{basename}"
        try:
            response = client.describe_stacks(StackName=stack_name)
            stack = response["Stacks"][0]
            status = stack["StackStatus"]
            last_updated = stack.get("LastUpdatedTime", stack.get("CreationTime"))
            marker = "[OK]" if is_healthy(status) else "[FAIL]"
            if not is_healthy(status):
                all_healthy = False
            print(f"{stack_name:<35} {marker + ' ' + status:<25} {last_updated}")
        except ClientError as error:
            if "does not exist" in str(error):
                print(f"{stack_name:<35} {'NOT_DEPLOYED':<25} -")
            else:
                print(f"{stack_name:<35} {'[FAIL] ' + str(error):<25}")
                all_healthy = False

    print("-" * 90)
    if not all_healthy:
        print("One or more stacks are unhealthy.")
        sys.exit(1)

    print("All deployed stacks are healthy.")


if __name__ == "__main__":
    main()
