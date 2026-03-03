import pytest
from heuristic_model.routing_engine import EmergencyRoutingModel

@pytest.fixture
def router():
    # Will use the dummy dataframe since db path doesn't exist during tests
    return EmergencyRoutingModel("dummy_test_db.csv")

def test_rank_hospitals_filtering(router):
    # Patient in NYC
    lat, lon = 40.7128, -74.0060
    
    # Requesting Cardiology
    res = router.rank_hospitals(lat, lon, {"severity": 3, "specialty": "Cardiology"})
    assert len(res) > 0
    # Both General City Hospital and Heart Center have Cardiology in dummy setup
    names = [r["name"] for r in res]
    assert "Heart Center" in names
    
    # Requesting Orthopedics
    res = router.rank_hospitals(lat, lon, {"severity": 2, "specialty": "Orthopedics"})
    assert len(res) == 1
    assert res[0]["name"] == "Mercy Trauma Center"

def test_rank_hospitals_sorting(router):
    lat, lon = 40.7128, -74.0060
    # Severity 5: ETA should be highest priority (80%)
    res = router.rank_hospitals(lat, lon, {"severity": 5, "specialty": "General"})
    
    assert len(res) > 0
    # The closest one should generally win for high severity
    # General City Hospital is exactly at 40.7128, -74.0060 so distance is 0.
    assert res[0]["name"] == "General City Hospital"
    assert res[0]["distance_km"] == 0.0

def test_rank_hospitals_empty_specialty(router):
    lat, lon = 40.7128, -74.0060
    # Requesting a specialty that doesn't exist
    res = router.rank_hospitals(lat, lon, {"severity": 3, "specialty": "Pediatrics"})
    assert len(res) == 0
