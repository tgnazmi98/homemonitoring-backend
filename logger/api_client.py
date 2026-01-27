import os
import requests
import json
import time
from typing import Dict, Any
from datetime import datetime

class APIClient:
    def __init__(self):
        self.base_url = os.getenv('API_BASE_URL', 'http://backend:8000')
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

    def send_meter_reading(self, meter_name: str, unix_timestamp: int, readings: Dict[str, float]) -> bool:
        """Send meter reading data to the API"""
        try:
            data = {
                'meter_name': meter_name,
                'timestamp': unix_timestamp,
                'readings': readings
            }

            response = self.session.post(
                f"{self.base_url}/api/ingest/",
                json=data,
                timeout=30
            )

            if response.status_code == 201:
                return True
            else:
                print(f"API error: {response.status_code} - {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"Failed to send data to API: {e}")
            return False

    def health_check(self) -> bool:
        """Check if the API is healthy"""
        try:
            response = self.session.get(
                f"{self.base_url}/health/",
                timeout=10
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False