# ABDM Emergency Response System — Prototype

Voice-first, multi-agent emergency dispatch prototype using Python + AWS.

---

## Architecture at a glance

```
Caller (mic) → Transcribe → Intake Agent (Bedrock Claude) → Polly (speaker)
                                     │
                        location confirmed ──────────────────────────────────────┐
                                     │                                           ▼
                              INTAKE_COMPLETE                          Dispatch Agent (parallel)
                                     │                                  dummy fleet + GPS sim
                                     ▼
                            Severity Agent (placeholder model)
                                     │
                                     ▼
                         Hospital Router Agent (placeholder scoring)
                                     │
                              QR code generated
                                     │
                             ACTIVE_TRANSPORT
                                     │
                        Paramedic scans QR & updates
                                     │
                              Re-routing (severity agent → hospital router)
```

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python      | 3.11+   |
| pip         | latest  |
| PortAudio   | system  |
| AWS account | any     |

### Install PortAudio (required for PyAudio / mic access)

**macOS:**
```bash
brew install portaudio
```

**Ubuntu / Debian:**
```bash
sudo apt-get install -y portaudio19-dev python3-pyaudio
```

**Windows:**
PyAudio wheels include PortAudio. No separate install needed.

---

## AWS Setup

### 1. IAM permissions
Your AWS user / role needs:

```json
{
  "Effect": "Allow",
  "Action": [
    "transcribe:StartStreamTranscription",
    "polly:SynthesizeSpeech",
    "bedrock:InvokeModel",
    "dynamodb:CreateTable",
    "dynamodb:PutItem",
    "dynamodb:GetItem",
    "dynamodb:UpdateTimeToLive",
    "dynamodb:DescribeTable",
    "location:SearchPlaceIndexForText"
  ],
  "Resource": "*"
}
```

### 2. Enable Claude on Amazon Bedrock
Go to: AWS Console → Bedrock → Model access → Request access to **Claude 3.5 Sonnet v2**
Region: `ap-south-1` (Mumbai) is recommended for India.

### 3. (Optional) Amazon Location Place Index
For real geocoding, create a Place Index in AWS Console:
- Name: `abdm-place-index`
- Data provider: Esri or HERE

Without it the system falls back to Bengaluru city-centre coordinates.

---

## Installation

```bash
# Clone / copy the project
cd abdm/

# Create virtualenv
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## Configuration

Create a `.env` file in the `abdm/` directory:

```env
# ── Required ──────────────────────────────────────────────
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here
AWS_REGION=ap-south-1

# ── Bedrock ────────────────────────────────────────────────
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0

# ── Polly voice (choose one) ───────────────────────────────
# Aditi = Hindi-English (hi-IN)   Raveena = Hindi (hi-IN)
# Kajal = Indian English (en-IN)
POLLY_VOICE_ID=Aditi
POLLY_LANGUAGE_CODE=hi-IN

# ── Transcribe language ────────────────────────────────────
TRANSCRIBE_LANGUAGE_CODE=en-IN

# ── DynamoDB ───────────────────────────────────────────────
DYNAMO_TABLE_NAME=abdm_sessions

# ── QR output directory ────────────────────────────────────
QR_OUTPUT_DIR=./output_qr

# ── Optional: real geocoding ───────────────────────────────
# LOCATION_PLACE_INDEX=abdm-place-index

# ── Optional: custom dummy ambulance fleet ─────────────────
# Format: lat:lon:unit_id  (comma-separated)
# DUMMY_AMBULANCE_FLEET=12.9716:77.5946:AMB-001,12.9352:77.6245:AMB-002
```

---

## Running the prototype

### Option A — Full voice pipeline (CLI)
```bash
cd abdm/
python main.py
```

What happens:
1. DynamoDB table auto-created if missing
2. Agent greets you and starts asking questions (Polly speaks, mic listens)
3. The moment you give a location → ambulance dispatch fires in parallel
4. After all fields collected → severity calculated → hospital selected
5. QR code PNG saved to `./output_qr/{session_id}.png`
6. Full summary printed to terminal

### Option B — Run the API server
```bash
cd abdm/
python main.py --api
# or
uvicorn main:app --reload --port 8000
```

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/session/{session_id}` | Full session state from DynamoDB |
| GET | `/track/{session_id}/{unit_id}` | Stub tracking (returns last known position) |
| POST | `/paramedic/update` | Paramedic severity update → triggers re-routing |

### Paramedic update example
```bash
curl -X POST http://localhost:8000/paramedic/update \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "ABC123",
    "severity_score": 1,
    "care_type": "cardiac",
    "stability_window": "< 10 min",
    "resources_needed": ["ECG", "defibrillator", "cardiologist"]
  }'
```

---

## Placeholder → Production swap guide

| Component | File | What to replace | With |
|-----------|------|-----------------|------|
| Severity model | `agents/severity_agent.py` | `_placeholder_severity_model()` | SageMaker `invoke_endpoint()` |
| Hospital match | `agents/hospital_router.py` | `_placeholder_hospital_match()` | RDS query + SageMaker ranker |
| Hospital DB | `agents/hospital_router.py` | `HOSPITAL_DB` list | Amazon RDS PostgreSQL |
| Ambulance fleet | `agents/dispatch_agent.py` | `_load_fleet()` | Fleet management DB / Location tracker |
| Dispatch command | `agents/dispatch_agent.py` | `send_dispatch_command()` | IoT Core MQTT publish |
| GPS stream | `agents/dispatch_agent.py` | `_simulate_gps_stream()` | IoT Core → Kinesis |
| Tracking URL | `agents/dispatch_agent.py` | `publish_tracking_url()` | API Gateway WebSocket |
| Prenotification | `agents/hospital_router.py` | `_send_prenotification()` | Amazon SNS / hospital API |
| Geocoding | `tools/location_tool.py` | fallback coords | Amazon Location Place Index |
| QR delivery | `tools/qr_tool.py` | local PNG | S3 signed URL + SMS via Pinpoint |

---

## Project structure

```
abdm/
├── main.py                 FastAPI app + CLI runner
├── orchestrator.py         State machine
├── models.py               Pydantic data contracts
├── config.py               Settings from .env
├── requirements.txt
├── .env                    ← create this (not committed)
├── output_qr/              ← QR PNGs appear here
├── agents/
│   ├── intake_agent.py     Voice conversation loop
│   ├── dispatch_agent.py   Ambulance dispatch (dummy fleet)
│   ├── severity_agent.py   Severity calc (placeholder)
│   └── hospital_router.py  Hospital match (placeholder)
└── tools/
    ├── bedrock_tool.py     Claude NLU + conversation
    ├── transcribe_tool.py  Mic → AWS Transcribe Streaming
    ├── polly_tool.py       AWS Polly → speaker
    ├── dynamo_tool.py      DynamoDB session store
    ├── location_tool.py    Geocoding (AWS Location)
    └── qr_tool.py          QR code generation
```

---

## Troubleshooting

**`No module named 'pyaudio'`**
→ Install PortAudio first (see Prerequisites), then `pip install pyaudio`

**`ResourceNotFoundException` on Bedrock**
→ Enable model access in AWS Bedrock console for your region

**`ValidationException` on Transcribe**
→ Verify `TRANSCRIBE_LANGUAGE_CODE` is a supported code (e.g. `en-IN`, `hi-IN`)

**Mic not picking up audio**
→ Check system mic permissions; test with `python -c "import pyaudio; print(pyaudio.PyAudio().get_device_count())"`

**DynamoDB `AccessDeniedException`**
→ Ensure your IAM user has `dynamodb:CreateTable`, `PutItem`, `GetItem` on `*`
