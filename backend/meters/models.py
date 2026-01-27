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
        ]

    def __str__(self):
        return f"{self.meter_name} - Energy at {self.timestamp}"
