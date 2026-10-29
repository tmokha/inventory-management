"""
Tests for restocking order API endpoints.
"""
import json
from datetime import datetime, timedelta

import pytest

import mock_data


@pytest.fixture(autouse=True)
def isolated_restocking_orders(tmp_path, monkeypatch):
    """Redirect restocking order writes to a temp dir and start each test empty."""
    monkeypatch.setattr(mock_data, "DATA_DIR", str(tmp_path))
    saved = list(mock_data.restocking_orders)
    # Clear in place: main.py holds a reference to this same list object
    mock_data.restocking_orders.clear()
    yield tmp_path
    mock_data.restocking_orders.clear()
    mock_data.restocking_orders.extend(saved)


def forecasts_by_sku(client):
    return {f["item_sku"]: f for f in client.get("/api/demand").json()}


class TestRestockingEndpoints:
    """Test suite for restocking order endpoints."""

    def test_demand_forecasts_include_cost_and_lead_time(self, client):
        """Test that every forecast has a unit cost and lead time for restocking."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        for forecast in response.json():
            assert isinstance(forecast["unit_cost"], (int, float))
            assert forecast["unit_cost"] > 0
            assert isinstance(forecast["lead_time_days"], int)
            assert forecast["lead_time_days"] > 0

    def test_get_all_restocking_orders_empty(self, client):
        """Test getting restocking orders when none have been submitted."""
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restocking_order(self, client):
        """Test submitting a valid restocking order."""
        forecasts = forecasts_by_sku(client)
        payload = {
            "budget": 100000,
            "items": [
                {"sku": "WDG-001", "quantity": 150},
                {"sku": "GSK-203", "quantity": 100},
            ],
        }

        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert order["budget"] == 100000
        assert len(order["items"]) == 2

        expected_total = sum(
            item["quantity"] * forecasts[item["sku"]]["unit_cost"]
            for item in payload["items"]
        )
        assert abs(order["total_value"] - expected_total) < 0.01

    def test_restocking_order_uses_server_prices(self, client):
        """Test that item names and prices come from forecast data."""
        forecasts = forecasts_by_sku(client)
        response = client.post(
            "/api/restocking-orders",
            json={"budget": 100000, "items": [{"sku": "FLT-405", "quantity": 10}]},
        )
        item = response.json()["items"][0]

        assert item["name"] == forecasts["FLT-405"]["item_name"]
        assert item["unit_cost"] == forecasts["FLT-405"]["unit_cost"]
        assert item["lead_time_days"] == forecasts["FLT-405"]["lead_time_days"]

    def test_restocking_order_lead_time_calculation(self, client):
        """Test that lead time is the slowest item and sets expected delivery."""
        forecasts = forecasts_by_sku(client)
        skus = ["WDG-001", "GSK-203", "CTL-330"]
        response = client.post(
            "/api/restocking-orders",
            json={"budget": 100000, "items": [{"sku": s, "quantity": 1} for s in skus]},
        )
        order = response.json()

        expected_lead = max(forecasts[s]["lead_time_days"] for s in skus)
        assert order["lead_time_days"] == expected_lead

        submitted = datetime.fromisoformat(order["submitted_date"])
        expected_delivery = datetime.fromisoformat(order["expected_delivery"])
        assert expected_delivery - submitted == timedelta(days=expected_lead)

    def test_created_order_appears_in_list_newest_first(self, client):
        """Test that submitted orders are listed with the newest first."""
        for quantity in (1, 2):
            client.post(
                "/api/restocking-orders",
                json={"budget": 1000, "items": [{"sku": "GSK-203", "quantity": quantity}]},
            )

        data = client.get("/api/restocking-orders").json()
        assert len(data) == 2
        assert data[0]["items"][0]["quantity"] == 2
        assert data[1]["items"][0]["quantity"] == 1
        assert data[0]["order_number"] != data[1]["order_number"]

    def test_restocking_order_persisted_to_file(self, client, isolated_restocking_orders):
        """Test that submitted orders are written to disk."""
        client.post(
            "/api/restocking-orders",
            json={"budget": 1000, "items": [{"sku": "GSK-203", "quantity": 5}]},
        )

        saved_file = isolated_restocking_orders / mock_data.RESTOCKING_ORDERS_FILE
        assert saved_file.exists()
        saved = json.loads(saved_file.read_text())
        assert len(saved) == 1
        assert saved[0]["items"][0]["sku"] == "GSK-203"

    def test_create_restocking_order_unknown_sku(self, client):
        """Test that an unknown SKU is rejected."""
        response = client.post(
            "/api/restocking-orders",
            json={"budget": 1000, "items": [{"sku": "NOPE-999", "quantity": 1}]},
        )
        assert response.status_code == 400
        assert "unknown sku" in response.json()["detail"].lower()

    def test_create_restocking_order_zero_quantity(self, client):
        """Test that a non-positive quantity is rejected."""
        response = client.post(
            "/api/restocking-orders",
            json={"budget": 1000, "items": [{"sku": "GSK-203", "quantity": 0}]},
        )
        assert response.status_code == 400

    def test_create_restocking_order_no_items(self, client):
        """Test that an order with no items is rejected."""
        response = client.post("/api/restocking-orders", json={"budget": 1000, "items": []})
        assert response.status_code == 400

    def test_create_restocking_order_over_budget(self, client):
        """Test that an order costing more than the budget is rejected and not stored."""
        response = client.post(
            "/api/restocking-orders",
            json={"budget": 10, "items": [{"sku": "MTR-304", "quantity": 1}]},
        )
        assert response.status_code == 400
        assert "exceeds budget" in response.json()["detail"].lower()
        assert client.get("/api/restocking-orders").json() == []
