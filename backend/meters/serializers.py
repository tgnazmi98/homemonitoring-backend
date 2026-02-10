from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Meter, PowerReading, EnergyReading, TariffRate, FuelAdjustment, ToUPeakHours, EfficiencyIncentiveTier
from django.utils import timezone
from datetime import datetime

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = fields

class MeterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Meter
        fields = '__all__'

class PowerReadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = PowerReading
        fields = '__all__'

class EnergyReadingSerializer(serializers.ModelSerializer):
    class Meta:
        model = EnergyReading
        fields = '__all__'

class MeterDataBulkSerializer(serializers.Serializer):
    meter_name = serializers.CharField(max_length=255)
    timestamp = serializers.IntegerField()  # Unix timestamp from logger
    readings = serializers.DictField()

    def create(self, validated_data):
        meter_name = validated_data['meter_name']
        timestamp_unix = validated_data['timestamp']
        readings = validated_data['readings']

        # Convert Unix timestamp to datetime
        timestamp = timezone.make_aware(datetime.fromtimestamp(timestamp_unix))

        # Energy parameters that go to energy_readings table
        energy_params = {
            'Import Active Energy': 'import_active_energy',
            'Export Active Energy': 'export_active_energy',
            'Import Reactive Energy': 'import_reactive_energy',
            'Export Reactive Energy': 'export_reactive_energy',
            'Total Active Energy': 'total_active_energy',
            'Total Reactive Energy': 'total_reactive_energy',
            'Power Demand': 'power_demand',
            'Maximum Power Demand': 'maximum_power_demand',
            'Current Demand': 'current_demand',
            'Maximum Current Demand': 'maximum_current_demand',
            'Active Power Demand': 'active_power_demand',
            'Maximum Active Power Demand': 'maximum_active_power_demand',
            'Apparent Power Demand': 'apparent_power_demand'
        }

        # Power parameters that go to power_readings table
        power_params = {
            'Voltage': 'voltage',
            'Current': 'current',
            'Active Power': 'active_power',
            'Apparent Power': 'apparent_power',
            'Reactive Power': 'reactive_power',
            'Power Factor': 'power_factor',
            'Phase Angle': 'phase_angle',
            'Frequency': 'frequency'
        }

        # Create energy reading if any energy parameters are present
        energy_data = {}
        for param, field in energy_params.items():
            if param in readings:
                energy_data[field] = readings[param]

        if energy_data:
            EnergyReading.objects.create(
                timestamp=timestamp,
                meter_name=meter_name,
                **energy_data
            )

        # Create power reading if any power parameters are present
        power_data = {}
        for param, field in power_params.items():
            if param in readings:
                power_data[field] = readings[param]

        if power_data:
            PowerReading.objects.create(
                timestamp=timestamp,
                meter_name=meter_name,
                **power_data
            )

        return validated_data


class TariffRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TariffRate
        fields = '__all__'


class FuelAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = FuelAdjustment
        fields = '__all__'


class ToUPeakHoursSerializer(serializers.ModelSerializer):
    class Meta:
        model = ToUPeakHours
        fields = '__all__'


class EfficiencyIncentiveTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = EfficiencyIncentiveTier
        fields = '__all__'