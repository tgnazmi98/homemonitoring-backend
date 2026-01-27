import os
import psycopg2
import psycopg2.extras
from datetime import datetime
from typing import Dict, List, Any, Optional
from contextlib import contextmanager

class DatabaseManager:
    def __init__(self, db_path: str = None):
        self.db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': os.getenv('DB_PORT', '5432'),
            'database': os.getenv('DB_NAME', 'electrical_monitoring'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', 'postgres')
        }
        self.init_database()

    @contextmanager
    def get_connection(self):
        conn = psycopg2.connect(**self.db_config)
        try:
            yield conn
        finally:
            conn.close()

    def init_database(self):
        """Initialize database tables if they don't exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create meter readings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meter_readings (
                    id SERIAL PRIMARY KEY,
                    timestamp BIGINT NOT NULL,
                    meter_name VARCHAR(255) NOT NULL,
                    parameter VARCHAR(255) NOT NULL,
                    value REAL,
                    uploaded INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create meters table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meters (
                    id SERIAL PRIMARY KEY,
                    meter_name VARCHAR(255) UNIQUE NOT NULL,
                    meter_id VARCHAR(255) NOT NULL,
                    model VARCHAR(255) NOT NULL,
                    function_code INTEGER NOT NULL,
                    last_successful_read BIGINT DEFAULT 0
                )
            """)
            
            # Create index for faster queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON meter_readings(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_readings_meter ON meter_readings(meter_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_readings_uploaded ON meter_readings(uploaded)")
            
            conn.commit()

    def save_meter_reading(self, unix_time: int, meter_name: str, readings: Dict[str, float]):
        """Save meter readings to database."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for parameter, value in readings.items():
                    cursor.execute("""
                        INSERT INTO meter_readings (timestamp, meter_name, parameter, value)
                        VALUES (%s, %s, %s, %s)
                    """, (unix_time, meter_name, parameter, value))
                conn.commit()
                
                
        except Exception as e:
            print(f"Error saving meter reading to database: {str(e)}")
            raise

    def update_meter_info(self, meter_name: str, meter_id: str, model: str, function_code: int):
        """Update meter information."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO meters (meter_name, meter_id, model, function_code)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (meter_name)
                DO UPDATE SET
                    meter_id = EXCLUDED.meter_id,
                    model = EXCLUDED.model,
                    function_code = EXCLUDED.function_code
            """, (meter_name, meter_id, model, function_code))
            conn.commit()

    def update_last_successful_read(self, meter_name: str, timestamp: int):
        """Update last successful read timestamp for a meter."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE meters
                SET last_successful_read = %s
                WHERE meter_name = %s
            """, (timestamp, meter_name))
            conn.commit()

    def get_unuploaded_readings(self, meter_name: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get readings that haven't been uploaded yet."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if meter_name:
                cursor.execute("""
                    SELECT timestamp, meter_name, parameter, value
                    FROM meter_readings
                    WHERE uploaded = 0 AND meter_name = %s
                    ORDER BY timestamp ASC
                    LIMIT %s
                """, (meter_name, limit))
            else:
                cursor.execute("""
                    SELECT timestamp, meter_name, parameter, value
                    FROM meter_readings
                    WHERE uploaded = 0
                    ORDER BY timestamp ASC
                    LIMIT %s
                """, (limit,))
            
            rows = cursor.fetchall()
            
            # Group readings by timestamp and meter
            readings = {}
            for timestamp, meter, param, value in rows:
                key = (timestamp, meter)
                if key not in readings:
                    readings[key] = {
                        "Time": timestamp,
                        "Meter": meter
                    }
                readings[key][param] = value  # Add parameter directly to top level
            
            return list(readings.values())

    def mark_readings_as_uploaded(self, timestamp: int, meter_name: str):
        """Mark readings as uploaded."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE meter_readings
                SET uploaded = 1
                WHERE timestamp = %s AND meter_name = %s
            """, (timestamp, meter_name))
            conn.commit()

    def cleanup_old_readings(self, days_to_keep: int = 30):
        """Delete readings older than specified days."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            timestamp_threshold = int(datetime.now().timestamp()) - (days_to_keep * 24 * 60 * 60)
            cursor.execute("""
                DELETE FROM meter_readings
                WHERE timestamp < %s AND uploaded = 1
            """, (timestamp_threshold,))
            conn.commit()

    def get_unuploaded_readings_in_timeframe(self, start_time: int, end_time: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get readings within a specific timeframe that haven't been uploaded yet.
        
        Args:
            start_time: Start timestamp (inclusive)
            end_time: End timestamp (inclusive)
            limit: Maximum number of readings to return
            
        Returns:
            List[Dict[str, Any]]: List of readings
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT timestamp, meter_name, parameter, value
                FROM meter_readings
                WHERE uploaded = 0
                AND timestamp >= %s
                AND timestamp <= %s
                ORDER BY timestamp ASC
                LIMIT %s
            """, (start_time, end_time, limit))
            
            rows = cursor.fetchall()
            
            # Group readings by timestamp and meter
            readings = {}
            for timestamp, meter, param, value in rows:
                key = (timestamp, meter)
                if key not in readings:
                    readings[key] = {
                        "Time": timestamp,
                        "Meter": meter
                    }
                readings[key][param] = value  # Add parameter directly to top level
            
            return list(readings.values())

    def get_unuploaded_5min_readings(self, limit: int = 100, location_id: int = None) -> List[Dict[str, Any]]:
        """Get unuploaded readings that were taken at 5-minute marks.
        
        Args:
            limit: Maximum number of readings to return
            
        Returns:
            List of readings as dictionaries with Time, Meter, and Parameters
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # First get all unique timestamps and meters that are at 5-minute marks and not uploaded
            cursor.execute("""
                SELECT DISTINCT timestamp, meter_name
                FROM meter_readings
                WHERE uploaded = 0
                ORDER BY timestamp ASC
                LIMIT %s
            """, (limit,))
            
            time_meter_pairs = cursor.fetchall()
            readings = []
            
            # For each timestamp and meter, get all parameters
            for timestamp, meter_name in time_meter_pairs:
                cursor.execute("""
                    SELECT parameter, value
                    FROM meter_readings
                    WHERE timestamp = %s AND meter_name = %s AND uploaded = 0
                """, (timestamp, meter_name))
                
                parameters = {}
                for param, value in cursor.fetchall():
                    parameters[param] = value
                
                if parameters:  # Only add if we have parameters
                    # Flatten the parameters to match Django API format
                    reading_data = {
                        "Time": timestamp,
                        "Meter": meter_name,
                        "Location_ID": location_id,
                        **parameters  # Flatten parameters to top level
                    }
                    readings.append(reading_data)
            
            return readings 