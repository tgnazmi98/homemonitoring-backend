from django.core.management.base import BaseCommand
from django.db import connection
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Setup TimescaleDB extensions and hypertables'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            try:
                # Enable TimescaleDB extension
                self.stdout.write('Creating TimescaleDB extension...')
                cursor.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")

                # Enable other necessary extensions
                cursor.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")

                # Convert tables to hypertables (must be done after tables exist)
                try:
                    self.stdout.write('Converting power_readings to hypertable...')
                    cursor.execute("""
                        SELECT create_hypertable('power_readings', 'timestamp', if_not_exists => TRUE);
                    """)
                except Exception as e:
                    if "already a hypertable" not in str(e):
                        logger.warning(f"Could not create hypertable for power_readings: {e}")

                try:
                    self.stdout.write('Converting energy_readings to hypertable...')
                    cursor.execute("""
                        SELECT create_hypertable('energy_readings', 'timestamp', if_not_exists => TRUE);
                    """)
                except Exception as e:
                    if "already a hypertable" not in str(e):
                        logger.warning(f"Could not create hypertable for energy_readings: {e}")

                # Add retention policies (3 years)
                try:
                    self.stdout.write('Setting up retention policies...')
                    cursor.execute("""
                        SELECT add_retention_policy('power_readings', INTERVAL '3 years', if_not_exists => TRUE);
                    """)
                    cursor.execute("""
                        SELECT add_retention_policy('energy_readings', INTERVAL '3 years', if_not_exists => TRUE);
                    """)
                except Exception as e:
                    logger.warning(f"Could not add retention policies: {e}")

                # Add compression policies
                try:
                    self.stdout.write('Setting up compression policies...')
                    cursor.execute("""
                        SELECT add_compression_policy('power_readings', INTERVAL '7 days', if_not_exists => TRUE);
                    """)
                    cursor.execute("""
                        SELECT add_compression_policy('energy_readings', INTERVAL '7 days', if_not_exists => TRUE);
                    """)
                except Exception as e:
                    logger.warning(f"Could not add compression policies: {e}")

                self.stdout.write(
                    self.style.SUCCESS('Successfully setup TimescaleDB extensions and hypertables')
                )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Error setting up TimescaleDB: {e}')
                )
                raise