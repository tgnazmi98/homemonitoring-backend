# Generated migration for billing models

from django.db import migrations, models
import django.db.models.deletion
from datetime import date, time


def add_initial_tariff_data(apps, schema_editor):
    """Add initial Malaysia tariff rates (effective 1 July 2025) and efficiency incentive tiers"""
    TariffRate = apps.get_model('meters', 'TariffRate')
    FuelAdjustment = apps.get_model('meters', 'FuelAdjustment')
    ToUPeakHours = apps.get_model('meters', 'ToUPeakHours')
    EfficiencyIncentiveTier = apps.get_model('meters', 'EfficiencyIncentiveTier')

    # Create General Tariff (effective 1 July 2025)
    general_tariff = TariffRate.objects.create(
        tariff_type='GENERAL',
        is_active=True,
        effective_from=date(2025, 7, 1),
        description='General Tariff - 2-tier pricing effective 1 July 2025',
        energy_rate_tier1_sen=27.03,  # ≤1500 kWh
        energy_rate_tier2_sen=37.03,  # >1500 kWh
        tier1_threshold_kwh=1500,
        capacity_rate_sen=4.55,
        network_rate_sen=12.85,
        retail_charge_rm=10.00,
        retail_waive_threshold_kwh=600,
    )

    # Create ToU Tariff (effective 1 July 2025)
    tou_tariff = TariffRate.objects.create(
        tariff_type='TOU',
        is_active=True,
        effective_from=date(2025, 7, 1),
        description='Time of Use Tariff - effective 1 July 2025',
        # Tier 1 (≤1500 kWh)
        energy_rate_tier1_peak_sen=28.52,      # Weekdays 14:00-22:00
        energy_rate_tier1_offpeak_sen=24.43,   # All other times + weekends
        # Tier 2 (>1500 kWh)
        energy_rate_tier2_peak_sen=38.52,      # Weekdays 14:00-22:00
        energy_rate_tier2_offpeak_sen=34.43,   # All other times + weekends
        tier1_threshold_kwh=1500,
        capacity_rate_sen=4.55,
        network_rate_sen=12.85,
        retail_charge_rm=10.00,
        retail_waive_threshold_kwh=600,
    )

    # Create ToU peak hours (weekdays 14:00-22:00)
    ToUPeakHours.objects.create(
        tariff_rate=tou_tariff,
        day_type='WEEKDAY',
        start_time=time(14, 0),
        end_time=time(22, 0),
        is_peak=True,
    )

    # Create initial Fuel Adjustment (January 2025)
    FuelAdjustment.objects.create(
        rate_sen_per_kwh=0.00,
        effective_month=date(2025, 1, 1),
        is_active=True,
        description='Initial AFA rate for January 2025',
    )

    # Create Energy Efficiency Incentive Tiers (for consumption <1000 kWh)
    tiers_data = [
        (1, 200, -25.0),
        (201, 250, -24.5),
        (251, 300, -22.5),
        (301, 350, -21.0),
        (351, 400, -17.0),
        (401, 450, -14.5),
        (451, 500, -12.0),
        (501, 550, -10.5),
        (551, 600, -9.0),
        (601, 650, -7.5),
        (651, 700, -5.5),
        (701, 750, -4.5),
        (751, 800, -4.0),
        (801, 850, -2.5),
        (851, 900, -1.0),
        (901, 1000, -0.5),
    ]

    for min_kwh, max_kwh, rebate in tiers_data:
        EfficiencyIncentiveTier.objects.create(
            min_kwh=min_kwh,
            max_kwh=max_kwh,
            rebate_sen_per_kwh=rebate,
            is_active=True,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('meters', '0003_rename_energy_readings_timestamp_idx_energy_read_timesta_019394_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='TariffRate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tariff_type', models.CharField(choices=[('GENERAL', 'General Tariff'), ('TOU', 'Time of Use (ToU)')], max_length=10)),
                ('is_active', models.BooleanField(default=True)),
                ('effective_from', models.DateField()),
                ('effective_to', models.DateField(blank=True, null=True)),
                ('description', models.TextField(blank=True)),
                ('energy_rate_tier1_sen', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('energy_rate_tier2_sen', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('tier1_threshold_kwh', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('energy_rate_tier1_peak_sen', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('energy_rate_tier1_offpeak_sen', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('energy_rate_tier2_peak_sen', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('energy_rate_tier2_offpeak_sen', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('capacity_rate_sen', models.DecimalField(decimal_places=2, max_digits=5)),
                ('network_rate_sen', models.DecimalField(decimal_places=2, max_digits=5)),
                ('retail_charge_rm', models.DecimalField(decimal_places=2, max_digits=6)),
                ('retail_waive_threshold_kwh', models.DecimalField(decimal_places=2, max_digits=6)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'tariff_rates',
            },
        ),
        migrations.CreateModel(
            name='FuelAdjustment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rate_sen_per_kwh', models.DecimalField(decimal_places=2, max_digits=5)),
                ('effective_month', models.DateField()),
                ('is_active', models.BooleanField(default=True)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'fuel_adjustments',
            },
        ),
        migrations.CreateModel(
            name='EfficiencyIncentiveTier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('min_kwh', models.DecimalField(decimal_places=2, max_digits=6)),
                ('max_kwh', models.DecimalField(decimal_places=2, max_digits=6)),
                ('rebate_sen_per_kwh', models.DecimalField(decimal_places=2, max_digits=5)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'efficiency_incentive_tiers',
                'ordering': ['min_kwh'],
            },
        ),
        migrations.CreateModel(
            name='ToUPeakHours',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('day_type', models.CharField(choices=[('WEEKDAY', 'Weekday (Monday-Friday)'), ('WEEKEND', 'Weekend (Saturday-Sunday)')], max_length=10)),
                ('start_time', models.TimeField()),
                ('end_time', models.TimeField()),
                ('is_peak', models.BooleanField()),
                ('tariff_rate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='peak_hours', to='meters.tariffrate')),
            ],
            options={
                'db_table': 'tou_peak_hours',
            },
        ),
        migrations.AddIndex(
            model_name='tariffrate',
            index=models.Index(fields=['tariff_type', '-effective_from'], name='tariff_rate_tariff_effective_idx'),
        ),
        migrations.AddIndex(
            model_name='fueladjustment',
            index=models.Index(fields=['-effective_month'], name='fuel_adjust_effective_month_idx'),
        ),
        # Add initial data
        migrations.RunPython(add_initial_tariff_data),
    ]
