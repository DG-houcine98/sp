"""
index_to_opensearch Lambda.

Triggered by the orders DynamoDB Stream. Upserts INSERT/MODIFY records into
OpenSearch (using order_id as the document id, so repeated updates overwrite
rather than duplicate) and deletes the document on REMOVE.

Authenticates to OpenSearch via AWSV4SignerAuth using this Lambda's own
execution-role credentials - no separate OpenSearch username/password to
store or rotate.
"""

import os

import boto3
from boto3.dynamodb.types import TypeDeserializer
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")
INDEX_NAME = "orders"

_deserializer = TypeDeserializer()


def _deserialize_image(dynamodb_image):
    """Converts a DynamoDB Stream record image ({"S": "value"} format) to plain Python types."""
    return {
        key: _deserializer.deserialize(value) for key, value in dynamodb_image.items()
    }


def _get_opensearch_client():
    credentials = boto3.Session().get_credentials()
    auth = AWSV4SignerAuth(credentials, AWS_REGION, "es")
    endpoint = os.environ["SEARCH_DOMAIN_ENDPOINT"]
    return OpenSearch(
        hosts=[{"host": endpoint, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )


def lambda_handler(event, context):
    client = _get_opensearch_client()

    for record in event.get("Records", []):
        event_name = record["eventName"]
        keys = _deserialize_image(record["dynamodb"]["Keys"])
        order_id = keys["order_id"]

        if event_name == "REMOVE":
            client.delete(index=INDEX_NAME, id=order_id, ignore=[404])
            continue

        new_image = _deserialize_image(record["dynamodb"]["NewImage"])
        client.index(index=INDEX_NAME, id=order_id, body=new_image)

    return {"statusCode": 200}
