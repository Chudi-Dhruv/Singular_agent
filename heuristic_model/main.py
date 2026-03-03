from fastapi import FastAPI, HTTPException
from .models import IncomingEmergencyRequest, HospitalResponse, HospitalRanked
from .aws_services import extract_clinical_constraints
from .routing_engine import EmergencyRoutingModel

app = FastAPI(title="ERE Backend", description="Emergency Routing Engine API")

# Initialize router with the dataset
router = EmergencyRoutingModel("hackathon_db.csv")

@app.post("/api/v1/route", response_model=HospitalResponse)
async def process_emergency(request: IncomingEmergencyRequest):
    try:
        # 1. Ask AWS Bedrock to turn the messy transcript into clean JSON
        clinical_data = extract_clinical_constraints(request.transcript)
        
        # 2. Pass that clean data + GPS to your Pandas routing engine
        top_hospitals = router.rank_hospitals(
            patient_lat=request.patient_lat,
            patient_lon=request.patient_lon,
            clinical_data=clinical_data
        )
        
        # Convert the dictionary output to the Pydantic models for validation
        validated_routes = [HospitalRanked(**h) for h in top_hospitals]

        # 3. Return the ranked list to the frontend
        return HospitalResponse(status="success", routes=validated_routes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
