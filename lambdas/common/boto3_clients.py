"""
Shared boto3 client construction for all Lambda handlers.

Clients are built once at module import time (not inside the handler function)
so they're reused across warm invocations of the same execution context -
recreating a boto3 client on every call adds latency for no benefit.

All resource identifiers come from environment variables injected by
CloudFormation (see cloudformation/04-compute-api.yaml) - never hardcode a
table name, queue URL, or endpoint here.
"""
import os

import boto3

AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")

dynamodb_client = boto3.client("dynamodb", region_name=AWS_REGION)
dynamodb_resource = boto3.resource("dynamodb", region_name=AWS_REGION)
sqs_client = boto3.client("sqs", region_name=AWS_REGION)
sns_client = boto3.client("sns", region_name=AWS_REGION)


def get_orders_table():
    """Returns the boto3 Table resource for the orders table."""
    table_name = os.environ["ORDERS_TABLE_NAME"]
    return dynamodb_resource.Table(table_name)
