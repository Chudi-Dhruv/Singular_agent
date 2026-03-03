import os
import pandas as pd
from typing import Dict, Any, List
from .aws_services import get_driving_eta

class EmergencyRoutingModel:
    def __init__(self, db_path: str = "hackathon_db.csv"):
        """
        Loads the enriched hospital database into a Pandas DataFrame.
        """
        if os.path.exists(db_path):
            self.hospitals_df = pd.read_csv(db_path)
        else:
            print(f"Warning: Database {db_path} not found. Using a dummy DataFrame.")
            # Create a basic dummy dataframe for testing if the real one isn't there
            self.hospitals_df = pd.DataFrame([
                {"id": 1, "name": "General City Hospital", "lat": 40.7128, "lon": -74.0060, "specialties": "General,Trauma,Cardiology", "quality_score": 85},
                {"id": 2, "name": "Heart Center", "lat": 40.7200, "lon": -74.0100, "specialties": "Cardiology", "quality_score": 92},
                {"id": 3, "name": "Neurology Institute", "lat": 40.7300, "lon": -73.9900, "specialties": "Neurology,General", "quality_score": 88},
                {"id": 4, "name": "Mercy Trauma Center", "lat": 40.7500, "lon": -73.9800, "specialties": "Trauma,Orthopedics", "quality_score": 90}
            ])

    def rank_hospitals(self, patient_lat: float, patient_lon: float, clinical_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Executes the MCDA formula to rank hospitals.
        Returns the top 3 results.
        clinical_data expects: {"severity": int, "specialty": str}
        """
        severity = clinical_data.get("severity", 3)
        required_specialty = clinical_data.get("specialty", "General")

        df = self.hospitals_df.copy()

        # ----------------------------------------------------------------
        # Stage 1: Filtering
        # ----------------------------------------------------------------
        # Drop hospitals that lack the required specialty
        # Assuming finding the specialty substring in a comma-separated list
        if "specialties" in df.columns:
            df = df[df["specialties"].str.contains(required_specialty, case=False, na=False)]

        if df.empty:
            return []

        # ----------------------------------------------------------------
        # Stage 2: Calculate ETA and Distance for the shortlist
        # ----------------------------------------------------------------
        etas = []
        distances = []
        for _, row in df.iterrows():
            h_lat = float(row['lat'])
            h_lon = float(row['lon'])
            route_info = get_driving_eta((patient_lat, patient_lon), (h_lat, h_lon))
            etas.append(route_info["eta_mins"])
            distances.append(route_info["distance_km"])
            
        df['eta_mins'] = etas
        df['distance_km'] = distances

        # ----------------------------------------------------------------
        # Stage 3: Min-Max Normalization
        # ----------------------------------------------------------------
        # For quality_score, higher is better
        # For eta, lower is better (so we invert it)
        if "quality_score" not in df.columns:
            df["quality_score"] = 50  # Default if missing
            
        q_min, q_max = df['quality_score'].min(), df['quality_score'].max()
        e_min, e_max = df['eta_mins'].min(), df['eta_mins'].max()

        def normalize(val, v_min, v_max, invert=False):
            if v_max == v_min:
                return 1.0 # Avoid division by zero, all same score
            norm = (val - v_min) / (v_max - v_min)
            return 1.0 - norm if invert else norm

        df['norm_quality'] = df['quality_score'].apply(lambda x: normalize(x, q_min, q_max, invert=False))
        df['norm_eta'] = df['eta_mins'].apply(lambda x: normalize(x, e_min, e_max, invert=True))

        # ----------------------------------------------------------------
        # Stage 4: Dynamic Weights based on Severity
        # ----------------------------------------------------------------
        # If severity is high (e.g., 4 or 5), ETA matters more (e.g., 80% weight).
        # If severity is low (e.g., 1 or 2), Quality matters more or is balanced.
        if severity >= 4:
            w_eta, w_quality = 0.8, 0.2
        elif severity == 3:
            w_eta, w_quality = 0.5, 0.5
        else:
            w_eta, w_quality = 0.3, 0.7

        df['mcda_score'] = (df['norm_eta'] * w_eta) + (df['norm_quality'] * w_quality)

        # ----------------------------------------------------------------
        # Stage 5: Sort and return Top 3
        # ----------------------------------------------------------------
        df_sorted = df.sort_values(by='mcda_score', ascending=False).head(3)

        results = []
        for _, row in df_sorted.iterrows():
            results.append({
                "name": row['name'],
                "distance_km": round(row['distance_km'], 2),
                "eta_mins": round(row['eta_mins'], 2),
                "score": round(row['mcda_score'], 4)
            })

        return results
