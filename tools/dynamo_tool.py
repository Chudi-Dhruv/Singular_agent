"""
tools/dynamo_tool.py
Persist and retrieve IncidentSession objects in DynamoDB.

Table schema:
  PK: session_id (String)
  TTL: expires_at (Number) — auto-delete after 24 h

The table is auto-created on first run if it doesn't exist.
"""

import json
import logging
import time
import boto3
from botocore.exceptions import ClientError

from config import settings
from models import IncidentSession

log = logging.getLogger(__name__)

_client = boto3.client(
    "dynamodb",
    region_name=settings.aws_region,
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
)
TABLE = settings.dynamo_table_name


# ── Table bootstrap ────────────────────────────────────────────────────────────

def ensure_table_exists() -> None:
    """Create the DynamoDB table if it doesn't already exist."""
    try:
        _client.describe_table(TableName=TABLE)
        log.info("DynamoDB table '%s' already exists.", TABLE)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        log.info("Creating DynamoDB table '%s' ...", TABLE)
        _client.create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "session_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        # Enable TTL
        waiter = _client.get_waiter("table_exists")
        waiter.wait(TableName=TABLE)
        _client.update_time_to_live(
            TableName=TABLE,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
        )
        log.info("Table '%s' created with TTL on expires_at.", TABLE)


# ── Read / Write ───────────────────────────────────────────────────────────────

def save_session(session: IncidentSession) -> None:
    """Serialise and upsert the session into DynamoDB."""
    session.updated_at = time.time()
    payload = session.model_dump_json()
    _client.put_item(
        TableName=TABLE,
        Item={
            "session_id": {"S": session.session_id},
            "data":       {"S": payload},
            "expires_at": {"N": str(int(time.time()) + 86400)},  # 24-hour TTL
        },
    )
    log.debug("Session %s saved (state=%s).", session.session_id, session.state)


def load_session(session_id: str) -> IncidentSession | None:
    """Load a session from DynamoDB; returns None if not found."""
    resp = _client.get_item(
        TableName=TABLE, Key={"session_id": {"S": session_id}}
    )
    item = resp.get("Item")
    if not item:
        return None
    return IncidentSession.model_validate_json(item["data"]["S"])
