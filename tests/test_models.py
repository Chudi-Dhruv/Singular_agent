import pytest
from heuristic_model.models import IncomingEmergencyRequest, ParsedClinicalData, HospitalRanked, HospitalResponse

def test_incoming_request_valid():
    req = IncomingEmergencyRequest(
        transcript="Patient is experiencing severe chest pain and requires immediate cardiology intervention.",
        patient_lat=40.7128,
        patient_lon=-74.0060
    )
    assert req.patient_lat == 40.7128
    assert req.patient_lon == -74.0060

def test_incoming_request_invalid():
    with pytest.raises(ValueError):
        # Missing required fields should raise validation error
        IncomingEmergencyRequest(transcript="Help!")

def test_parsed_clinical_data():
    data = ParsedClinicalData(severity=5, specialty="Cardiology")
    assert data.severity == 5
    assert data.specialty == "Cardiology"

def test_hospital_response():
    ranked = HospitalRanked(
        name="Heart Center",
        distance_km=2.5,
        eta_mins=6.0,
        score=0.95
    )
    res = HospitalResponse(status="success", routes=[ranked])
    assert len(res.routes) == 1
    assert res.routes[0].name == "Heart Center"
