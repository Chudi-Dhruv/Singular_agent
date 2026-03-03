import json
import boto3
from geopy.distance import geodesic
from typing import Tuple, Dict, Any

# Initialize AWS clients lazily or globally
try:
    bedrock_runtime = boto3.client('bedrock-runtime', region_name='us-east-1')
    location_client = boto3.client('location', region_name='us-east-1')
except Exception as e:
    print(f"Warning: Failed to initialize AWS clients. {e}")
    bedrock_runtime = None
    location_client = None

def extract_clinical_constraints(transcript: str) -> Dict[str, Any]:
    """
    Sends the paramedic's voice transcript to Amazon Bedrock (Claude 3)
    and returns a structured JSON dictionary (severity, specialty).
    """
    if not bedrock_runtime:
        # Fallback dummy data if AWS isn't configured for the hackathon local testing
        return {"severity": 3, "specialty": "General"}

    # Use Claude 3 Haiku or Sonnet
    model_id = 'anthropic.claude-3-haiku-20240307-v1:0'
    prompt = f"""
    Analyze the following paramedic transcript and extract the clinical constraints.
    Return strictly a JSON object with two keys:
    - severity: An integer from 1 (least severe) to 5 (most severe).
    - specialty: The required medical specialty (e.g., "Cardiology", "Trauma", "General", "Neurology").
    
    Transcript: "{transcript}"
    """
    
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 100,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    })

    try:
        response = bedrock_runtime.invoke_model(
            modelId=model_id,
            body=body,
            accept='application/json',
            contentType='application/json'
        )
        response_body = json.loads(response.get('body').read())
        content_text = response_body.get('content', [{}])[0].get('text', '{}')
        
        # Claude might wrap JSON in backticks, but let's assume raw or parse carefully
        # Simple extraction for demo:
        return json.loads(content_text)
    except Exception as e:
        print(f"Bedrock API failed: {e}")
        # Fallback to general assessment
        return {"severity": 3, "specialty": "General"}


def get_driving_eta(start_coords: Tuple[float, float], end_coords: Tuple[float, float]) -> Dict[str, float]:
    """
    Pings Amazon Location Service to get ETA and distance.
    Returns: {"eta_mins": float, "distance_km": float}
    fallback to geopy haversine distance if it fails.
    start_coords: (lat, lon)
    end_coords: (lat, lon)
    """
    # Note: longitude, latitude expected by Amazon Location Routes usually is [lon, lat]
    try:
        if location_client is None:
            raise ValueError("Location client not initialized")
            
        # Example using calculate_route (assuming a calculator name is set up, e.g., 'HackathonRouteCalculator')
        calculator_name = 'HackathonRouteCalculator'
        
        response = location_client.calculate_route(
            CalculatorName=calculator_name,
            DeparturePosition=[start_coords[1], start_coords[0]],
            DestinationPosition=[end_coords[1], end_coords[0]],
            DistanceUnit='Kilometers'
        )
        
        distance = response['Summary']['Distance']
        duration_seconds = response['Summary']['DurationSeconds']
        
        return {
            "eta_mins": duration_seconds / 60.0,
            "distance_km": distance
        }
        
    except Exception as e:
        print(f"Location Service failed: {e}. Falling back to Haversine.")
        
        # Fallback using geopy's geodesic distance (Haversine)
        distance_km = geodesic(start_coords, end_coords).kilometers
        # Rough estimate: 40 km/h average speed in city
        # time = distance / speed
        eta_mins = (distance_km / 40.0) * 60
        
        return {
            "eta_mins": round(eta_mins, 2),
            "distance_km": round(distance_km, 2)
        }
