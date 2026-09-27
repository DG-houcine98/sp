"""
Shared pytest fixtures. Uses moto's mock_aws to fake DynamoDB/SQS/SNS entirely
in-memory - no real AWS calls, no credentials required, tests run in
milliseconds.

`mock_aws_context` is the single fixture that actually starts moto's mock -
all other fixtures depend on it and create resources inside that same mock,
rather than each opening its own `with mock_aws():` block. Stacking multiple
independent mock_aws() context managers per test is a known moto footgun;
one shared context per test avoids it.
"""
import importlib.util
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

TEST_REGION = "eu-west-1"
TEST_TABLE_NAME = "test-orders"

LAMBDAS_DIR = Path(__file__).resolve().parent.parent / "lambdas"

# lambdas/common must be importable as `common.*` from inside each handler -
# add lambdas/ (the common package's parent) to sys.path once, here.
if str(LAMBDAS_DIR) not in sys.path:
    sys.path.insert(0, str(LAMBDAS_DIR))


def load_handler_module(function_dir_name):
    """
    Loads lambdas/<function_dir_name>/handler.py as a uniquely-named module.

    Every Lambda function's file is named handler.py, so a plain `import
    handler` would collide between functions - this loads each one directly
    from its file path instead, under a distinct module name.

    Also drops any cached `common.*` modules first: common/boto3_clients.py
    builds its boto3 clients at import time, so a module cached from a
    previous test would hold clients bound to that test's (already exited)
    moto mock, and would try hitting real AWS if reused here.
    """
    for cached_name in [name for name in sys.modules if name == "common" or name.startswith("common.")]:
        del sys.modules[cached_name]

    module_name = f"{function_dir_name}_handler"
    handler_path = LAMBDAS_DIR / function_dir_name / "handler.py"
    spec = importlib.util.spec_from_file_location(module_name, handler_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """moto still needs *some* credentials present in the environment, even fake ones."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", TEST_REGION)
    monkeypatch.setenv("AWS_REGION", TEST_REGION)


@pytest.fixture
def mock_aws_context():
    with mock_aws():
        yield


@pytest.fixture
def orders_table(mock_aws_context, monkeypatch):
    monkeypatch.setenv("ORDERS_TABLE_NAME", TEST_TABLE_NAME)
    client = boto3.client("dynamodb", region_name=TEST_REGION)
    client.create_table(
        TableName=TEST_TABLE_NAME,
        AttributeDefinitions=[{"AttributeName": "order_id", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "order_id", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    yield boto3.resource("dynamodb", region_name=TEST_REGION).Table(TEST_TABLE_NAME)


@pytest.fixture
def orders_queue(mock_aws_context, monkeypatch):
    client = boto3.client("sqs", region_name=TEST_REGION)
    queue = client.create_queue(QueueName="test-orders-queue")
    monkeypatch.setenv("ORDERS_QUEUE_URL", queue["QueueUrl"])
    yield queue["QueueUrl"]


@pytest.fixture
def orders_topic(mock_aws_context, monkeypatch):
    client = boto3.client("sns", region_name=TEST_REGION)
    topic = client.create_topic(Name="test-orders-topic")
    monkeypatch.setenv("ORDERS_TOPIC_ARN", topic["TopicArn"])
    yield topic["TopicArn"]
