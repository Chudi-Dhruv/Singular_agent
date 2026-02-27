"""
tools/qr_tool.py
Generate a QR code PNG containing the full case summary JSON.
The paramedic scans this on arrival to get the pre-computed case on their MDT app.

Output: PNG file saved to QR_OUTPUT_DIR/{session_id}.png
Returns the file path.
"""

import json
import logging
import os

import qrcode
from qrcode.image.pure import PyPNGImage

from config import settings

log = logging.getLogger(__name__)


def generate_qr(session_id: str, case_payload: dict) -> str:
    """
    Encode case_payload as JSON into a QR code PNG.
    Returns the absolute path to the generated PNG.
    """
    os.makedirs(settings.qr_output_dir, exist_ok=True)
    out_path = os.path.join(settings.qr_output_dir, f"{session_id}.png")

    payload_str = json.dumps(case_payload, default=str)

    qr = qrcode.QRCode(
        version=None,                  # auto-size
        error_correction=qrcode.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(payload_str)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img.save(out_path)

    log.info("[QR] Generated QR for session %s → %s", session_id, out_path)
    return out_path
