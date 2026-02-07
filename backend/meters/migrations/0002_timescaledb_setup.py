# Generated migration for TimescaleDB setup
# This migration documents the conversion of power_readings and energy_readings tables
# to TimescaleDB hypertables and the addition of related policies and indexes.
#
# NOTE: Composite Primary Key
# ===========================
# The TimescaleDB hypertable conversion automatically creates a composite primary key:
#   PRIMARY KEY (id, timestamp)
#
# Django's ORM is unaware of the composite key constraint and treats 'id' as the sole
# primary key. This is acceptable because:
#   - 'id' is still unique and functions as a primary key for Django's ORM
#   - TimescaleDB requires the composite key internally for time-series partitioning
#   - Django queries continue to work correctly with this configuration
#
# All operations in this migration are idempotent and designed to be run on databases
# that have already had TimescaleDB setup applied via the setup_timescaledb management command.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('meters', '0001_initial'),
    ]

    operations = [
        # Enable TimescaleDB extension (idempotent)
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS timescaledb;",
            reverse_sql=migrations.RunSQL.noop,  # Don't drop extension during rollback
        ),

        # Convert power_readings to hypertable (idempotent)
        # This will fail gracefully if already a hypertable
        migrations.RunSQL(
            sql="SELECT create_hypertable('power_readings', 'timestamp', if_not_exists => TRUE);",
            reverse_sql=migrations.RunSQL.noop,
        ),

        # Convert energy_readings to hypertable (idempotent)
        # This will fail gracefully if already a hypertable
        migrations.RunSQL(
            sql="SELECT create_hypertable('energy_readings', 'timestamp', if_not_exists => TRUE);",
            reverse_sql=migrations.RunSQL.noop,
        ),

        # Add timestamp indexes (created automatically by TimescaleDB hypertable conversion)
        # These indexes optimize time-series queries
        migrations.AddIndex(
            model_name='powerreading',
            index=models.Index(fields=['-timestamp'], name='power_readings_timestamp_idx'),
        ),
        migrations.AddIndex(
            model_name='energyreading',
            index=models.Index(fields=['-timestamp'], name='energy_readings_timestamp_idx'),
        ),

        # Add retention policies (3 years)
        # Automatically delete data older than 3 years
        migrations.RunSQL(
            sql="SELECT add_retention_policy('power_readings', INTERVAL '3 years', if_not_exists => TRUE);",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="SELECT add_retention_policy('energy_readings', INTERVAL '3 years', if_not_exists => TRUE);",
            reverse_sql=migrations.RunSQL.noop,
        ),

        # Add compression policies (7 days)
        # Compress chunks older than 7 days for better storage efficiency
        migrations.RunSQL(
            sql="SELECT add_compression_policy('power_readings', INTERVAL '7 days', if_not_exists => TRUE);",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="SELECT add_compression_policy('energy_readings', INTERVAL '7 days', if_not_exists => TRUE);",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
