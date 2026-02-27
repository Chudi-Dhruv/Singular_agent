"""
tools/aws_client.py
===================
Central boto3 client factory.

On SageMaker the execution role provides credentials automatically.
When keys ARE set (local dev), they are passed explicitly.
This prevents passing None values to boto3 which would cause auth errors.
"""

import boto3
from config import settings


def make_client(service: str):
    """Return a boto3 client using IAM role (SageMaker) or explicit keys (local)."""
    kwargs = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"]     = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client(service, **kwargs)