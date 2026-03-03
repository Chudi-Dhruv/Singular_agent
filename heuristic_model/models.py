from pydantic import BaseModel, Field
from typing import List

class IncomingEmergencyRequest(BaseModel):
    transcript: str = Field(..., description="The paramedic's voice transcript")
    patient_lat: float = Field(..., description="Latitude of the emergency location")
    patient_lon: float = Field(..., description="Longitude of the emergency location")

class ParsedClinicalData(BaseModel):
    severity: int = Field(..., description="Calculated severity from the transcript (e.g., 1-5)")
    specialty: str = Field(..., description="Required medical specialty based on transcript")

class HospitalRanked(BaseModel):
    name: str = Field(..., description="Name of the hospital")
    distance_km: float = Field(..., description="Distance in kilometers")
    eta_mins: float = Field(..., description="Estimated arrival time in minutes")
    score: float = Field(..., description="Calculated MCDA score for ranking")

class HospitalResponse(BaseModel):
    status: str = Field("success", description="Status of the request")
    routes: List[HospitalRanked] = Field(..., description="Ranked list of top hospitals")
