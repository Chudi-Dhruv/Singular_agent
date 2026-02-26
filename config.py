"""
config.py
All configuration loaded from environment / .env file.
Create a .env file in the project root (see README).
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # ── AWS Core ─────────────────────────────────────────────────────────────
    aws_region: str = Field("ap-south-1", env="AWS_REGION")
    aws_access_key_id: str = Field(..., env="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(..., env="AWS_SECRET_ACCESS_KEY")

    # ── Bedrock ───────────────────────────────────────────────────────────────
    bedrock_model_id: str = Field(
        "anthropic.claude-3-5-sonnet-20241022-v2:0", env="BEDROCK_MODEL_ID"
    )

    # ── Polly ─────────────────────────────────────────────────────────────────
    polly_voice_id: str = Field("Aditi", env="POLLY_VOICE_ID")   # Hindi-English voice
    polly_language_code: str = Field("hi-IN", env="POLLY_LANGUAGE_CODE")

    # ── Transcribe ────────────────────────────────────────────────────────────
    transcribe_language_code: str = Field("en-IN", env="TRANSCRIBE_LANGUAGE_CODE")
    transcribe_sample_rate: int = Field(16000, env="TRANSCRIBE_SAMPLE_RATE")

    # ── DynamoDB ──────────────────────────────────────────────────────────────
    dynamo_table_name: str = Field("abdm_sessions", env="DYNAMO_TABLE_NAME")

    # ── QR / Output ───────────────────────────────────────────────────────────
    qr_output_dir: str = Field("./output_qr", env="QR_OUTPUT_DIR")

    # ── Dummy Fleet ───────────────────────────────────────────────────────────
    # Comma-separated lat:lon:unit_id  (Bengaluru area defaults)
    dummy_ambulance_fleet: str = Field(
        "12.9716:77.5946:AMB-001,12.9352:77.6245:AMB-002,12.9611:77.6387:AMB-003",
        env="DUMMY_AMBULANCE_FLEET",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
