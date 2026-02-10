from django.db import models

class Meter(models.Model):
    meter_name = models.CharField(max_length=255, unique=True)
    meter_id = models.CharField(max_length=255)
    model = models.CharField(max_length=255)
    function_code = models.IntegerField()
    last_successful_read = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.meter_name

class PowerReading(models.Model):
    timestamp = models.DateTimeField()
    meter_name = models.CharField(max_length=255)
    voltage = models.FloatField(null=True, blank=True)
    current = models.FloatField(null=True, blank=True)
    active_power = models.FloatField(null=True, blank=True)
    apparent_power = models.FloatField(null=True, blank=True)
    reactive_power = models.FloatField(null=True, blank=True)
    power_factor = models.FloatField(null=True, blank=True)
    phase_angle = models.FloatField(null=True, blank=True)
    frequency = models.FloatField(null=True, blank=True)
    uploaded = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'power_readings'
        indexes = [
            models.Index(fields=['meter_name', '-timestamp']),
            models.Index(fields=['uploaded']),
            models.Index(fields=['-timestamp']),
        ]

    def __str__(self):
        return f"{self.meter_name} - Power at {self.timestamp}"

class EnergyReading(models.Model):
    timestamp = models.DateTimeField()
    meter_name = models.CharField(max_length=255)
    import_active_energy = models.FloatField(null=True, blank=True)
    export_active_energy = models.FloatField(null=True, blank=True)
    import_reactive_energy = models.FloatField(null=True, blank=True)
    export_reactive_energy = models.FloatField(null=True, blank=True)
    total_active_energy = models.FloatField(null=True, blank=True)
    total_reactive_energy = models.FloatField(null=True, blank=True)
    power_demand = models.FloatField(null=True, blank=True)
    maximum_power_demand = models.FloatField(null=True, blank=True)
    current_demand = models.FloatField(null=True, blank=True)
    maximum_current_demand = models.FloatField(null=True, blank=True)
    active_power_demand = models.FloatField(null=True, blank=True)
    maximum_active_power_demand = models.FloatField(null=True, blank=True)
    apparent_power_demand = models.FloatField(null=True, blank=True)
    uploaded = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'energy_readings'
        indexes = [
            models.Index(fields=['meter_name', '-timestamp']),
            models.Index(fields=['uploaded']),
            models.Index(fields=['-timestamp']),
        ]

    def __str__(self):
        return f"{self.meter_name} - Energy at {self.timestamp}"


class TariffRate(models.Model):
    """Malaysia Residential Tariff Rates (General and ToU)"""
    TARIFF_CHOICES = [
        ('GENERAL', 'General Tariff'),
        ('TOU', 'Time of Use (ToU)'),
    ]

    tariff_type = models.CharField(max_length=10, choices=TARIFF_CHOICES)
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True)

    # General Tariff rates (2-tier pricing)
    energy_rate_tier1_sen = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # 27.03
    energy_rate_tier2_sen = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # 37.03
    tier1_threshold_kwh = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)    # 1500

    # ToU Tariff rates (also 2-tier based on consumption)
    # Tier 1 (≤1500 kWh)
    energy_rate_tier1_peak_sen = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)      # 28.52
    energy_rate_tier1_offpeak_sen = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)   # 24.43
    # Tier 2 (>1500 kWh)
    energy_rate_tier2_peak_sen = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)      # 38.52
    energy_rate_tier2_offpeak_sen = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)   # 34.43

    # Common charges (both tariffs)
    capacity_rate_sen = models.DecimalField(max_digits=5, decimal_places=2)                                  # 4.55
    network_rate_sen = models.DecimalField(max_digits=5, decimal_places=2)                                   # 12.85
    retail_charge_rm = models.DecimalField(max_digits=6, decimal_places=2)                                   # 10.00
    retail_waive_threshold_kwh = models.DecimalField(max_digits=6, decimal_places=2)                         # 600

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tariff_rates'
        indexes = [
            models.Index(fields=['tariff_type', '-effective_from']),
        ]

    def __str__(self):
        return f"{self.get_tariff_type_display()} - {self.effective_from}"


class FuelAdjustment(models.Model):
    """Monthly Fuel Adjustment (AFA) rates"""
    rate_sen_per_kwh = models.DecimalField(max_digits=5, decimal_places=2)
    effective_month = models.DateField()  # First day of month
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'fuel_adjustments'
        indexes = [
            models.Index(fields=['-effective_month']),
        ]

    def __str__(self):
        return f"AFA {self.effective_month.strftime('%Y-%m')} - {self.rate_sen_per_kwh} sen/kWh"


class ToUPeakHours(models.Model):
    """Time of Use (ToU) peak and off-peak hour definitions"""
    DAY_TYPE_CHOICES = [
        ('WEEKDAY', 'Weekday (Monday-Friday)'),
        ('WEEKEND', 'Weekend (Saturday-Sunday)'),
    ]

    tariff_rate = models.ForeignKey(TariffRate, on_delete=models.CASCADE, related_name='peak_hours')
    day_type = models.CharField(max_length=10, choices=DAY_TYPE_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_peak = models.BooleanField()

    class Meta:
        db_table = 'tou_peak_hours'

    def __str__(self):
        return f"{self.get_day_type_display()} {self.start_time}-{self.end_time} ({'Peak' if self.is_peak else 'Off-peak'})"


class EfficiencyIncentiveTier(models.Model):
    """Energy Efficiency Incentive tiered rebate structure (for consumption <1000 kWh)"""
    min_kwh = models.DecimalField(max_digits=6, decimal_places=2)
    max_kwh = models.DecimalField(max_digits=6, decimal_places=2)
    rebate_sen_per_kwh = models.DecimalField(max_digits=5, decimal_places=2)  # Negative value
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'efficiency_incentive_tiers'
        ordering = ['min_kwh']

    def __str__(self):
        return f"{self.min_kwh}-{self.max_kwh} kWh: {self.rebate_sen_per_kwh} sen/kWh"
