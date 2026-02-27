"""
config.py
=========
All configuration loaded from environment / .env file.

On SageMaker Studio the execution role provides AWS credentials automatically
via the instance metadata service — you do NOT need to set AWS_ACCESS_KEY_ID
or AWS_SECRET_ACCESS_KEY. They are optional here for local dev use only.
"""

from __future__ import annotations
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # ── AWS Core ──────────────────────────────────────────────────────────────
    # Keys are OPTIONAL on SageMaker — the IAM execution role handles auth.
    # Set them in .env only when running locally without an IAM role.
    aws_region: str = Field("eu-north-1", env="AWS_REGION")
    aws_access_key_id:     Optional[str] = Field(None, env="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: Optional[str] = Field(None, env="AWS_SECRET_ACCESS_KEY")

    # ── Bedrock ───────────────────────────────────────────────────────────────
    bedrock_model_id: str = Field(
        "anthropic.claude-3-5-sonnet-20241022-v2:0", env="BEDROCK_MODEL_ID"
    )

    # ── Polly ─────────────────────────────────────────────────────────────────
    polly_voice_id:     str = Field("Aditi", env="POLLY_VOICE_ID")
    polly_language_code: str = Field("hi-IN", env="POLLY_LANGUAGE_CODE")

    # ── Transcribe ────────────────────────────────────────────────────────────
    transcribe_language_code: str = Field("en-IN", env="TRANSCRIBE_LANGUAGE_CODE")
    transcribe_sample_rate:   int = Field(16000,   env="TRANSCRIBE_SAMPLE_RATE")

    # ── DynamoDB ──────────────────────────────────────────────────────────────
    dynamo_table_name: str = Field("abdm_sessions", env="DYNAMO_TABLE_NAME")

    # ── QR / Output ───────────────────────────────────────────────────────────
    qr_output_dir: str = Field("./output_qr", env="QR_OUTPUT_DIR")

    # ── Dummy Fleet (Bengaluru) ───────────────────────────────────────────────
    dummy_ambulance_fleet: str = Field(
        "12.9716:77.5946:AMB-001,12.9352:77.6245:AMB-002,12.9611:77.6387:AMB-003",
        env="DUMMY_AMBULANCE_FLEET",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()