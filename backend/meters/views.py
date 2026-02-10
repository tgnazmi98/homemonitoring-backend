from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.http import JsonResponse, HttpResponse
from django.db.models import Q, Avg, Sum, Min, Max
from django.db.models.functions import TruncSecond
from django.utils import timezone
from datetime import timedelta, datetime
import pandas as pd
import io
import pytz
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Meter, PowerReading, EnergyReading, TariffRate, FuelAdjustment, ToUPeakHours, EfficiencyIncentiveTier
from .serializers import MeterSerializer, PowerReadingSerializer, EnergyReadingSerializer, MeterDataBulkSerializer, UserSerializer, TariffRateSerializer, FuelAdjustmentSerializer

# UTC+8 timezone for Malaysia
LOCAL_TZ = pytz.timezone('Asia/Kuala_Lumpur')

class MeterViewSet(viewsets.ModelViewSet):
    queryset = Meter.objects.all()
    serializer_class = MeterSerializer
    permission_classes = [IsAuthenticated]

class PowerReadingViewSet(viewsets.ModelViewSet):
    queryset = PowerReading.objects.all()
    serializer_class = PowerReadingSerializer
    permission_classes = [IsAuthenticated]

class EnergyReadingViewSet(viewsets.ModelViewSet):
    queryset = EnergyReading.objects.all()
    serializer_class = EnergyReadingSerializer
    permission_classes = [IsAuthenticated]

@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    return Response({'status': 'healthy'}, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    """Get current authenticated user info"""
    serializer = UserSerializer(request.user)
    return Response(serializer.data)

def get_readings_summary_sync():
    """Get readings summary synchronously for WebSocket broadcast."""
    power_summary = {}
    power_readings = PowerReading.objects.values('meter_name').distinct()
    for meter in power_readings:
        meter_name = meter['meter_name']
        latest_power = PowerReading.objects.filter(
            meter_name=meter_name
        ).order_by('-timestamp').first()

        if latest_power:
            power_summary[meter_name] = {
                'meter_name': meter_name,
                'latest_power_timestamp': latest_power.timestamp.isoformat() if latest_power.timestamp else None,
                'voltage': latest_power.voltage,
                'current': latest_power.current,
                'active_power': (latest_power.active_power or 0),
                'frequency': latest_power.frequency
            }

    energy_summary = {}
    energy_readings = EnergyReading.objects.values('meter_name').distinct()
    for meter in energy_readings:
        meter_name = meter['meter_name']
        latest_energy = EnergyReading.objects.filter(
            meter_name=meter_name
        ).order_by('-timestamp').first()

        if latest_energy:
            energy_summary[meter_name] = {
                'meter_name': meter_name,
                'latest_energy_timestamp': latest_energy.timestamp.isoformat() if latest_energy.timestamp else None,
                'import_active_energy': latest_energy.import_active_energy,
                'export_active_energy': latest_energy.export_active_energy,
                'power_demand': latest_energy.power_demand
            }

    summary = []
    all_meters = set(power_summary.keys()) | set(energy_summary.keys())
    for meter_name in all_meters:
        meter_data = {'meter_name': meter_name}

        if meter_name in power_summary:
            meter_data.update(power_summary[meter_name])

        if meter_name in energy_summary:
            meter_data.update(energy_summary[meter_name])

        latest_time = None
        if 'latest_power_timestamp' in meter_data and meter_data['latest_power_timestamp']:
            latest_time = meter_data['latest_power_timestamp']

        if latest_time:
            meter_data['status'] = 'online'

        summary.append(meter_data)

    return summary


def get_realtime_data_sync(meter_name):
    """Get real-time data for a specific meter."""
    latest_power = PowerReading.objects.filter(
        meter_name=meter_name
    ).order_by('-timestamp').first()

    latest_energy = EnergyReading.objects.filter(
        meter_name=meter_name
    ).order_by('-timestamp').first()

    if not latest_power and not latest_energy:
        return None

    realtime_data = {
        'meter_name': meter_name,
        'timezone': 'UTC+8'
    }

    if latest_power:
        local_time = convert_to_local_time(latest_power.timestamp)
        realtime_data.update({
            'timestamp': latest_power.timestamp.isoformat(),
            'local_time': local_time.isoformat(),
            'voltage': latest_power.voltage,
            'current': latest_power.current,
            'active_power': (latest_power.active_power or 0),
            'apparent_power': (latest_power.apparent_power or 0),
            'reactive_power': (latest_power.reactive_power or 0),
            'power_factor': latest_power.power_factor,
            'frequency': latest_power.frequency
        })

    if latest_energy:
        realtime_data.update({
            'import_active_energy': latest_energy.import_active_energy,
            'export_active_energy': latest_energy.export_active_energy,
            'power_demand': latest_energy.power_demand,
            'maximum_power_demand': latest_energy.maximum_power_demand
        })

    return realtime_data


def get_timeseries_point_sync(meter_name):
    """Get the latest timeseries data point for charts."""
    latest_power = PowerReading.objects.filter(
        meter_name=meter_name
    ).order_by('-timestamp').first()

    if not latest_power:
        return None

    return {
        'meter_name': meter_name,
        'timestamp': latest_power.timestamp.isoformat(),
        'active_power': latest_power.active_power or 0,
        'voltage': latest_power.voltage or 0,
        'current': latest_power.current or 0,
        'power_factor': latest_power.power_factor or 0,
        'frequency': latest_power.frequency or 0
    }


def broadcast_readings_update(meter_name=None):
    """Broadcast all real-time data to connected WebSocket clients."""
    channel_layer = get_channel_layer()

    # Get summary data
    summary = get_readings_summary_sync()

    # Build realtime data for all meters or specific meter
    realtime_data = {}
    timeseries_points = {}

    meter_names = [meter_name] if meter_name else [m['meter_name'] for m in summary]

    for name in meter_names:
        rt_data = get_realtime_data_sync(name)
        if rt_data:
            realtime_data[name] = rt_data

        ts_point = get_timeseries_point_sync(name)
        if ts_point:
            timeseries_points[name] = ts_point

    # Send combined update
    async_to_sync(channel_layer.group_send)(
        'readings',
        {
            'type': 'readings_update',
            'data': {
                'type': 'full_update',
                'summary': summary,
                'realtime': realtime_data,
                'timeseries_point': timeseries_points
            }
        }
    )


@api_view(['POST'])
@permission_classes([AllowAny])  # Logger uses internal Docker network, no auth needed
def ingest_meter_data(request):
    """
    API endpoint for logger to send meter data.
    Expected format:
    {
        "meter_name": "Main",
        "timestamp": 1640995200,
        "readings": {
            "Voltage": 230.5,
            "Current": 10.2,
            "Active Power": 2351.0,
            "Import Active Energy": 12345.67
        }
    }
    """
    serializer = MeterDataBulkSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        meter_name = request.data.get('meter_name')
        broadcast_readings_update(meter_name)
        return Response({'status': 'success'}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
def meter_readings_summary(request):
    # Get latest power readings for each meter
    power_summary = {}
    power_readings = PowerReading.objects.values('meter_name').distinct()
    for meter in power_readings:
        meter_name = meter['meter_name']
        latest_power = PowerReading.objects.filter(
            meter_name=meter_name
        ).order_by('-timestamp').first()

        if latest_power:
            power_summary[meter_name] = {
                'meter_name': meter_name,
                'latest_power_timestamp': latest_power.timestamp,
                'latest_power_reading': latest_power.created_at,
                'voltage': latest_power.voltage,
                'current': latest_power.current,
                'active_power': (latest_power.active_power or 0),  # Keep in W
                'frequency': latest_power.frequency
            }

    # Get latest energy readings for each meter
    energy_summary = {}
    energy_readings = EnergyReading.objects.values('meter_name').distinct()
    for meter in energy_readings:
        meter_name = meter['meter_name']
        latest_energy = EnergyReading.objects.filter(
            meter_name=meter_name
        ).order_by('-timestamp').first()

        if latest_energy:
            energy_summary[meter_name] = {
                'meter_name': meter_name,
                'latest_energy_timestamp': latest_energy.timestamp,
                'latest_energy_reading': latest_energy.created_at,
                'import_active_energy': latest_energy.import_active_energy,
                'export_active_energy': latest_energy.export_active_energy,
                'power_demand': latest_energy.power_demand
            }

    # Combine summaries
    summary = []
    all_meters = set(power_summary.keys()) | set(energy_summary.keys())
    for meter_name in all_meters:
        meter_data = {'meter_name': meter_name}

        if meter_name in power_summary:
            meter_data.update(power_summary[meter_name])

        if meter_name in energy_summary:
            meter_data.update(energy_summary[meter_name])

        # Determine overall status based on most recent reading
        latest_time = None
        if 'latest_power_reading' in meter_data:
            latest_time = meter_data['latest_power_reading']
        if 'latest_energy_reading' in meter_data:
            if latest_time is None or meter_data['latest_energy_reading'] > latest_time:
                latest_time = meter_data['latest_energy_reading']

        if latest_time:
            time_diff = timezone.now() - latest_time
            meter_data['status'] = 'online' if time_diff < timedelta(minutes=5) else 'offline'
            meter_data['latest_reading_time'] = latest_time

        summary.append(meter_data)

    return Response(summary)

@api_view(['GET'])
def meter_historical_data(request, meter_name):
    """Get historical data for a specific meter"""
    hours = int(request.GET.get('hours', 24))
    start_time = timezone.now() - timedelta(hours=hours)

    power_data = PowerReading.objects.filter(
        meter_name=meter_name,
        timestamp__gte=start_time
    ).order_by('timestamp')

    energy_data = EnergyReading.objects.filter(
        meter_name=meter_name,
        timestamp__gte=start_time
    ).order_by('timestamp')

    return Response({
        'power_readings': PowerReadingSerializer(power_data, many=True).data,
        'energy_readings': EnergyReadingSerializer(energy_data, many=True).data
    })

@api_view(['GET'])
def timeseries_data(request, meter_name):
    """Get time series data for charts"""
    # Support both hours and minutes parameters
    minutes = request.GET.get('minutes')
    hours = request.GET.get('hours')

    if minutes:
        start_time = timezone.now() - timedelta(minutes=int(minutes))
    elif hours:
        start_time = timezone.now() - timedelta(hours=int(hours))
    else:
        start_time = timezone.now() - timedelta(hours=24)

    power_data = PowerReading.objects.filter(
        meter_name=meter_name,
        timestamp__gte=start_time
    ).order_by('timestamp').values(
        'timestamp', 'voltage', 'current', 'active_power',
        'power_factor', 'frequency'
    )

    energy_data = EnergyReading.objects.filter(
        meter_name=meter_name,
        timestamp__gte=start_time
    ).order_by('timestamp').values(
        'timestamp', 'import_active_energy', 'export_active_energy',
        'power_demand', 'total_active_energy'
    )

    return Response({
        'power_timeseries': list(power_data),
        'energy_timeseries': list(energy_data)
    })

def convert_to_local_time(dt):
    """Convert datetime to local timezone (UTC+8)"""
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(LOCAL_TZ)

def calculate_energy_delta(readings, energy_field):
    """Calculate energy consumption deltas from cumulative readings.

    For a single-phase 63A @ 230V system:
    - Max power: ~14.5 kW
    - Max consumption per minute: 0.24 kWh
    - Max consumption per hour: 14.5 kWh

    We filter out suspicious deltas that exceed physical limits.
    """
    if len(readings) < 2:
        return []

    # Maximum allowed delta per reading based on time gap
    # For 63A @ 230V system, max is ~14.5 kW = 14.5 kWh per hour
    MAX_KWH_PER_HOUR = 15.0  # Slightly above theoretical max for margin

    deltas = []
    for i in range(1, len(readings)):
        prev_reading = readings[i-1]
        curr_reading = readings[i]

        prev_energy = prev_reading.get(energy_field, 0) or 0
        curr_energy = curr_reading.get(energy_field, 0) or 0

        # Calculate time gap in hours
        time_gap_hours = (curr_reading['timestamp'] - prev_reading['timestamp']).total_seconds() / 3600

        # Skip if time gap is too small (duplicate reading) or too large (missing data)
        if time_gap_hours < 0.0001:  # Less than 0.36 seconds
            continue
        if time_gap_hours > 2:  # Gap larger than 2 hours - skip to avoid false deltas
            continue

        # Calculate delta
        if curr_energy < prev_energy:
            # Meter reset or bad reading - skip this delta
            # Don't assume the current value is consumption
            continue
        else:
            delta = curr_energy - prev_energy

        # Calculate maximum allowed delta based on time gap
        max_allowed_delta = MAX_KWH_PER_HOUR * time_gap_hours

        # Filter out suspicious deltas
        if delta > max_allowed_delta:
            # Delta exceeds physical limit - likely bad data, skip
            continue

        # Skip zero or negligible deltas
        if delta < 0.0001:
            continue

        # Convert timestamp to local time
        local_time = convert_to_local_time(curr_reading['timestamp'])

        deltas.append({
            'timestamp': curr_reading['timestamp'],
            'local_time': local_time.isoformat(),
            'consumption': delta,
            'period_hours': time_gap_hours
        })

    return deltas

@api_view(['GET'])
def power_quality_data(request, meter_name):
    """Get power quality data with 30-minute averages for past 24 hours"""
    try:
        # Get time range (default: last 24 hours)
        hours = int(request.GET.get('hours', 24))
        start_time = timezone.now() - timedelta(hours=hours)

        # Get power readings
        power_readings = PowerReading.objects.filter(
            meter_name=meter_name,
            timestamp__gte=start_time
        ).order_by('timestamp')

        if not power_readings.exists():
            return Response({'error': 'No power data found'}, status=404)

        # Group by 30-minute intervals in local timezone
        aggregated_data = []
        current_readings = []
        interval_start = None

        for reading in power_readings:
            local_time = convert_to_local_time(reading.timestamp)

            # Round to 30-minute interval
            minute = local_time.minute
            rounded_minute = 0 if minute < 30 else 30
            interval_time = local_time.replace(minute=rounded_minute, second=0, microsecond=0)

            if interval_start is None:
                interval_start = interval_time

            # If we've moved to a new interval, aggregate the previous one
            if interval_time != interval_start and current_readings:
                avg_data = {
                    'timestamp': interval_start.astimezone(pytz.utc).isoformat(),
                    'local_time': interval_start.isoformat(),
                    'voltage': sum(r.voltage or 0 for r in current_readings) / len(current_readings),
                    'current': sum(r.current or 0 for r in current_readings) / len(current_readings),
                    'active_power': (sum(r.active_power or 0 for r in current_readings) / len(current_readings)),  # Keep in W
                    'apparent_power': (sum(r.apparent_power or 0 for r in current_readings) / len(current_readings)),  # Keep in VA
                    'reactive_power': (sum(r.reactive_power or 0 for r in current_readings) / len(current_readings)),  # Keep in VAr
                    'power_factor': sum(r.power_factor or 0 for r in current_readings) / len(current_readings),
                    'frequency': sum(r.frequency or 0 for r in current_readings) / len(current_readings),
                    'readings_count': len(current_readings)
                }
                aggregated_data.append(avg_data)
                current_readings = []
                interval_start = interval_time

            current_readings.append(reading)

        # Don't forget the last interval
        if current_readings:
            avg_data = {
                'timestamp': interval_start.astimezone(pytz.utc).isoformat(),
                'local_time': interval_start.isoformat(),
                'voltage': sum(r.voltage or 0 for r in current_readings) / len(current_readings),
                'current': sum(r.current or 0 for r in current_readings) / len(current_readings),
                'active_power': (sum(r.active_power or 0 for r in current_readings) / len(current_readings)),  # Keep in W
                'apparent_power': (sum(r.apparent_power or 0 for r in current_readings) / len(current_readings)),  # Keep in VA
                'reactive_power': (sum(r.reactive_power or 0 for r in current_readings) / len(current_readings)),  # Keep in VAr
                'power_factor': sum(r.power_factor or 0 for r in current_readings) / len(current_readings),
                'frequency': sum(r.frequency or 0 for r in current_readings) / len(current_readings),
                'readings_count': len(current_readings)
            }
            aggregated_data.append(avg_data)

        return Response({
            'meter_name': meter_name,
            'period': '30min',
            'timezone': 'UTC+8',
            'data': aggregated_data
        })

    except Exception as e:
        return Response({'error': str(e)}, status=500)

@api_view(['GET'])
def energy_consumption_data(request, meter_name):
    """Get energy consumption data with delta calculations"""
    try:
        period = request.GET.get('period', '30min')  # 30min, daily, monthly
        range_param = request.GET.get('range', '24h')  # 24h, 15d, 12m

        # Determine time range
        if range_param == '24h':
            start_time = timezone.now() - timedelta(hours=24)
        elif range_param == '15d':
            start_time = timezone.now() - timedelta(days=15)
        elif range_param == '12m':
            start_time = timezone.now() - timedelta(days=365)
        else:
            start_time = timezone.now() - timedelta(hours=24)

        # Get energy readings
        energy_readings = EnergyReading.objects.filter(
            meter_name=meter_name,
            timestamp__gte=start_time
        ).order_by('timestamp').values(
            'timestamp', 'import_active_energy', 'export_active_energy',
            'import_reactive_energy', 'export_reactive_energy'
        )

        if not energy_readings:
            return Response({'error': 'No energy data found'}, status=404)

        readings_list = list(energy_readings)

        # Calculate deltas for different energy types
        import_deltas = calculate_energy_delta(readings_list, 'import_active_energy')
        export_deltas = calculate_energy_delta(readings_list, 'export_active_energy')

        if period == 'daily' and range_param in ['15d', '12m']:
            # Aggregate deltas by day
            daily_consumption = {}
            for delta in import_deltas:
                local_time = datetime.fromisoformat(delta['local_time'].replace('+08:00', ''))
                date_key = local_time.date().isoformat()

                if date_key not in daily_consumption:
                    daily_consumption[date_key] = {
                        'date': date_key,
                        'import_energy': 0,
                        'export_energy': 0
                    }
                daily_consumption[date_key]['import_energy'] += delta['consumption']

            for delta in export_deltas:
                local_time = datetime.fromisoformat(delta['local_time'].replace('+08:00', ''))
                date_key = local_time.date().isoformat()

                if date_key in daily_consumption:
                    daily_consumption[date_key]['export_energy'] += delta['consumption']

            consumption_data = list(daily_consumption.values())

        elif period == 'monthly' and range_param == '12m':
            # Aggregate deltas by month
            monthly_consumption = {}
            for delta in import_deltas:
                local_time = datetime.fromisoformat(delta['local_time'].replace('+08:00', ''))
                month_key = f"{local_time.year}-{local_time.month:02d}"

                if month_key not in monthly_consumption:
                    monthly_consumption[month_key] = {
                        'month': month_key,
                        'import_energy': 0,
                        'export_energy': 0
                    }
                monthly_consumption[month_key]['import_energy'] += delta['consumption']

            for delta in export_deltas:
                local_time = datetime.fromisoformat(delta['local_time'].replace('+08:00', ''))
                month_key = f"{local_time.year}-{local_time.month:02d}"

                if month_key in monthly_consumption:
                    monthly_consumption[month_key]['export_energy'] += delta['consumption']

            consumption_data = list(monthly_consumption.values())

        else:
            # Aggregate deltas into 30-minute buckets
            half_hourly_consumption = {}

            for import_delta in import_deltas:
                local_time = datetime.fromisoformat(import_delta['local_time'].replace('+08:00', ''))
                # Round to 30-minute interval
                minute = local_time.minute
                rounded_minute = 0 if minute < 30 else 30
                interval_time = local_time.replace(minute=rounded_minute, second=0, microsecond=0)
                interval_key = interval_time.isoformat()

                if interval_key not in half_hourly_consumption:
                    half_hourly_consumption[interval_key] = {
                        'local_time': interval_key,
                        'import_energy': 0,
                        'export_energy': 0
                    }
                half_hourly_consumption[interval_key]['import_energy'] += import_delta['consumption']

            for export_delta in export_deltas:
                local_time = datetime.fromisoformat(export_delta['local_time'].replace('+08:00', ''))
                minute = local_time.minute
                rounded_minute = 0 if minute < 30 else 30
                interval_time = local_time.replace(minute=rounded_minute, second=0, microsecond=0)
                interval_key = interval_time.isoformat()

                if interval_key in half_hourly_consumption:
                    half_hourly_consumption[interval_key]['export_energy'] += export_delta['consumption']

            # Calculate net consumption and sort by time
            consumption_data = []
            for interval_key in sorted(half_hourly_consumption.keys()):
                item = half_hourly_consumption[interval_key]
                item['net_consumption'] = item['import_energy'] - item['export_energy']
                consumption_data.append(item)

        return Response({
            'meter_name': meter_name,
            'period': period,
            'range': range_param,
            'timezone': 'UTC+8',
            'consumption_data': consumption_data
        })

    except Exception as e:
        return Response({'error': str(e)}, status=500)

@api_view(['GET'])
def realtime_data(request, meter_name):
    """Get latest real-time readings for a meter"""
    try:
        # Get latest power reading
        latest_power = PowerReading.objects.filter(
            meter_name=meter_name
        ).order_by('-timestamp').first()

        # Get latest energy reading
        latest_energy = EnergyReading.objects.filter(
            meter_name=meter_name
        ).order_by('-timestamp').first()

        if not latest_power and not latest_energy:
            return Response({'error': 'No data found'}, status=404)

        # Prepare real-time data
        realtime_data = {
            'meter_name': meter_name,
            'timezone': 'UTC+8'
        }

        if latest_power:
            local_time = convert_to_local_time(latest_power.timestamp)
            realtime_data.update({
                'timestamp': latest_power.timestamp.isoformat(),
                'local_time': local_time.isoformat(),
                'voltage': latest_power.voltage,
                'current': latest_power.current,
                'active_power': (latest_power.active_power or 0),  # Keep in W
                'apparent_power': (latest_power.apparent_power or 0),  # Keep in VA
                'reactive_power': (latest_power.reactive_power or 0),  # Keep in VAr
                'power_factor': latest_power.power_factor,
                'frequency': latest_power.frequency
            })

        if latest_energy:
            realtime_data.update({
                'import_active_energy': latest_energy.import_active_energy,
                'export_active_energy': latest_energy.export_active_energy,
                'power_demand': latest_energy.power_demand,
                'maximum_power_demand': latest_energy.maximum_power_demand
            })

        return Response(realtime_data)

    except Exception as e:
        return Response({'error': str(e)}, status=500)


def calculate_efficiency_incentive(consumption_kwh):
    """Calculate energy efficiency incentive rebate for consumption <1000 kWh"""
    consumption_kwh = float(consumption_kwh)

    if consumption_kwh >= 1000:
        return 0.0

    tiers = EfficiencyIncentiveTier.objects.filter(is_active=True).order_by('min_kwh')
    total_rebate = 0.0

    for tier in tiers:
        min_kwh = float(tier.min_kwh)
        max_kwh = float(tier.max_kwh)
        rebate_rate = float(tier.rebate_sen_per_kwh)

        if consumption_kwh < min_kwh:
            break

        kwh_in_tier = min(consumption_kwh, max_kwh) - min_kwh + 1
        tier_rebate = float(kwh_in_tier) * rebate_rate / 100  # Convert sen to RM

        total_rebate += tier_rebate

    return float(abs(total_rebate))  # Return as positive value (discount)


def calculate_general_tariff_billing(consumption_kwh, billing_month):
    """Calculate General Tariff billing with 2-tier energy pricing"""
    try:
        tariff = TariffRate.objects.filter(
            tariff_type='GENERAL',
            is_active=True,
            effective_from__lte=billing_month
        ).order_by('-effective_from').first()

        if not tariff:
            return None

        afa = FuelAdjustment.objects.filter(
            effective_month__year=billing_month.year,
            effective_month__month=billing_month.month,
            is_active=True
        ).first()

        afa_rate = float(afa.rate_sen_per_kwh) if afa else 0
        consumption_kwh = float(consumption_kwh)

        # Determine energy rate based on consumption tier
        tier1_threshold = float(tariff.tier1_threshold_kwh or 1500)

        if consumption_kwh <= tier1_threshold:
            energy_rate_sen = float(tariff.energy_rate_tier1_sen or 27.03)
            tier = 'tier1'
        else:
            energy_rate_sen = float(tariff.energy_rate_tier2_sen or 37.03)
            tier = 'tier2'

        capacity_rate = float(tariff.capacity_rate_sen or 4.55)
        network_rate = float(tariff.network_rate_sen or 12.85)
        retail_waive_threshold = float(tariff.retail_waive_threshold_kwh or 600)
        retail_charge = float(tariff.retail_charge_rm or 10.00) if consumption_kwh > retail_waive_threshold else 0.0

        # Calculate charges (all as float)
        energy_charge = float(consumption_kwh * energy_rate_sen / 100)
        capacity_charge = float(consumption_kwh * capacity_rate / 100)
        network_charge = float(consumption_kwh * network_rate / 100)
        afa_charge = float(consumption_kwh * afa_rate / 100)

        subtotal = float(energy_charge + capacity_charge + network_charge + afa_charge + retail_charge)
        efficiency_incentive = float(calculate_efficiency_incentive(consumption_kwh))
        subtotal_after_incentive = float(subtotal - efficiency_incentive)

        # Calculate KWTB charge (1.6% of subtotal before incentive)
        kwtb_charge = float(subtotal * 0.016)

        total = float(subtotal_after_incentive + kwtb_charge)

        return {
            'consumption_kwh': round(consumption_kwh, 2),
            'energy_tier': tier,
            'energy_rate_sen': round(energy_rate_sen, 2),
            'energy_charge_rm': round(energy_charge, 2),
            'capacity_charge_rm': round(capacity_charge, 2),
            'network_charge_rm': round(network_charge, 2),
            'afa_charge_rm': round(afa_charge, 2),
            'retail_charge_rm': round(retail_charge, 2),
            'efficiency_incentive_rm': round(efficiency_incentive, 2),
            'subtotal_before_incentive_rm': round(subtotal, 2),
            'kwtb_charge_rm': round(kwtb_charge, 2),
            'total_amount_rm': round(total, 2),
        }
    except Exception as e:
        print(f"Error calculating general tariff: {e}")
        import traceback
        traceback.print_exc()
        return None


def find_reading_near_time(readings, target_datetime, tolerance_minutes=15):
    """
    Find the reading closest to target_datetime within tolerance.

    Args:
        readings: List of readings with timestamp and import_active_energy
        target_datetime: Target datetime to find reading near
        tolerance_minutes: Maximum minutes away from target (default 15)

    Returns:
        float: import_active_energy value, or None if no reading within tolerance
    """
    tolerance = timedelta(minutes=tolerance_minutes)
    closest_reading = None
    closest_diff = None

    for reading in readings:
        time_diff = abs(reading['timestamp'] - target_datetime)
        if time_diff <= tolerance:
            if closest_diff is None or time_diff < closest_diff:
                closest_diff = time_diff
                closest_reading = reading['import_active_energy']

    return closest_reading


def calculate_tou_billing(energy_readings, billing_month):
    """
    Simplified TOU billing calculation using boundary-based peak consumption.

    Gets readings at peak period boundaries (14:00-22:00 local time) to calculate
    peak consumption per weekday, avoiding complex per-reading timestamp analysis.

    Args:
        energy_readings: QuerySet or list of EnergyReading objects with timestamp and import_active_energy
        billing_month: datetime.date object for billing month lookup

    Returns:
        Dictionary with billing breakdown including peak/off-peak split, or None on error
    """
    try:
        # Get all readings as list for easier processing
        readings = list(energy_readings) if not isinstance(energy_readings, list) else energy_readings

        if len(readings) < 2:
            return None

        # Ensure we have timestamp and import_active_energy fields
        readings_with_values = []
        for r in readings:
            if isinstance(r, dict):
                readings_with_values.append(r)
            else:
                # Convert model instance to dict
                readings_with_values.append({
                    'timestamp': r.timestamp,
                    'import_active_energy': r.import_active_energy
                })

        readings = readings_with_values

        # Total consumption = last reading - first reading
        first_reading = float(readings[0]['import_active_energy'] or 0)
        last_reading = float(readings[-1]['import_active_energy'] or 0)
        total_kwh = last_reading - first_reading

        if total_kwh <= 0:
            return None

        # Get tariff rates
        tariff = TariffRate.objects.filter(
            tariff_type='TOU',
            is_active=True,
            effective_from__lte=billing_month
        ).order_by('-effective_from').first()

        if not tariff:
            return None

        # Get AFA rate
        afa = FuelAdjustment.objects.filter(
            effective_month__year=billing_month.year,
            effective_month__month=billing_month.month,
            is_active=True
        ).first()

        afa_rate = float(afa.rate_sen_per_kwh) if afa else 0

        # Calculate peak consumption by finding readings at peak boundaries
        peak_kwh_total = 0.0

        # Get billing period date range (20th of start month to 19th of end month)
        # For AFA lookup: if billing_month is 2024-02-01, the billing period is
        # 2024-01-20 to 2024-02-19, and we use Feb AFA
        start_month = billing_month.month
        start_year = billing_month.year

        # Determine the actual billing period start and end dates
        if start_month == 12:
            end_month = 1
            end_year = start_year + 1
        else:
            end_month = start_month + 1
            end_year = start_year

        # Billing starts on 20th of current month
        period_start = LOCAL_TZ.localize(datetime(start_year, start_month, 20, 0, 0, 0))
        # Billing ends on 19th of next month at 23:59:59
        period_end = LOCAL_TZ.localize(datetime(end_year, end_month, 19, 23, 59, 59))

        # Iterate through each weekday in the period
        current_date = period_start.date()
        end_date = period_end.date()

        while current_date <= end_date:
            # Only process weekdays (Monday=0 to Friday=4)
            if current_date.weekday() < 5:
                # Peak hours: 14:00 to 22:00 local time
                peak_start_dt = LOCAL_TZ.localize(datetime.combine(
                    current_date,
                    datetime.min.time().replace(hour=14, minute=0, second=0)
                ))

                peak_end_dt = LOCAL_TZ.localize(datetime.combine(
                    current_date,
                    datetime.min.time().replace(hour=22, minute=0, second=0)
                ))

                # Find readings near these times
                reading_at_start = find_reading_near_time(readings, peak_start_dt)
                reading_at_end = find_reading_near_time(readings, peak_end_dt)

                # If both readings exist, calculate peak consumption for this day
                if reading_at_start is not None and reading_at_end is not None:
                    day_peak_kwh = reading_at_end - reading_at_start
                    if day_peak_kwh > 0:  # Sanity check
                        peak_kwh_total += day_peak_kwh

            current_date += timedelta(days=1)

        # Off-peak is remainder
        offpeak_kwh = max(0, total_kwh - peak_kwh_total)

        # Determine tier based on total consumption
        tier1_threshold = float(tariff.tier1_threshold_kwh or 1500)

        if total_kwh <= tier1_threshold:
            tier = 'tier1'
            peak_rate = float(tariff.energy_rate_tier1_peak_sen or 28.52)
            offpeak_rate = float(tariff.energy_rate_tier1_offpeak_sen or 24.43)
        else:
            tier = 'tier2'
            peak_rate = float(tariff.energy_rate_tier2_peak_sen or 38.52)
            offpeak_rate = float(tariff.energy_rate_tier2_offpeak_sen or 34.43)

        # Calculate charges
        energy_charge_peak = float(peak_kwh_total * peak_rate / 100)
        energy_charge_offpeak = float(offpeak_kwh * offpeak_rate / 100)
        energy_charge_total = float(energy_charge_peak + energy_charge_offpeak)

        capacity_rate = float(tariff.capacity_rate_sen or 4.55)
        network_rate = float(tariff.network_rate_sen or 12.85)
        capacity_charge = float(total_kwh * capacity_rate / 100)
        network_charge = float(total_kwh * network_rate / 100)
        afa_charge = float(total_kwh * afa_rate / 100)

        # Retail charge
        retail_waive_threshold = float(tariff.retail_waive_threshold_kwh or 600)
        retail_charge = float(tariff.retail_charge_rm or 10.00) if total_kwh > retail_waive_threshold else 0.0

        subtotal = float(energy_charge_total + capacity_charge + network_charge + afa_charge + retail_charge)

        # Efficiency incentive (if consumption < 1000 kWh)
        efficiency_incentive = float(calculate_efficiency_incentive(total_kwh))

        # KWTB charge (1.6% of subtotal before incentive)
        kwtb_charge = float(subtotal * 0.016)

        total = float(subtotal - efficiency_incentive + kwtb_charge)

        return {
            'consumption_kwh': round(total_kwh, 2),
            'energy_tier': tier,
            'tou_breakdown': {
                'peak_kwh': round(peak_kwh_total, 2),
                'peak_rate_sen': round(peak_rate, 2),
                'peak_cost_rm': round(energy_charge_peak, 2),
                'offpeak_kwh': round(offpeak_kwh, 2),
                'offpeak_rate_sen': round(offpeak_rate, 2),
                'offpeak_cost_rm': round(energy_charge_offpeak, 2),
                'total_energy_charge_rm': round(energy_charge_total, 2),
            },
            'capacity_charge_rm': round(capacity_charge, 2),
            'network_charge_rm': round(network_charge, 2),
            'afa_charge_rm': round(afa_charge, 2),
            'retail_charge_rm': round(retail_charge, 2),
            'efficiency_incentive_rm': round(efficiency_incentive, 2),
            'subtotal_before_incentive_rm': round(subtotal, 2),
            'kwtb_charge_rm': round(kwtb_charge, 2),
            'total_amount_rm': round(total, 2),
        }
    except Exception as e:
        print(f"Error calculating ToU billing: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_billing_period_key(dt):
    """
    Get billing period key (20/MM - 19/MM format).
    Returns string like '2024-01~2024-02' for period 20 Jan - 19 Feb
    """
    local_time = convert_to_local_time(dt) if hasattr(dt, 'tzinfo') else dt

    day = local_time.day
    year = local_time.year
    month = local_time.month

    # If day is 20-31, billing period starts this month
    if day >= 20:
        period_start_month = month
        period_start_year = year

        # Handle month overflow (Dec 20 - Jan 19)
        if month == 12:
            period_end_month = 1
            period_end_year = year + 1
        else:
            period_end_month = month + 1
            period_end_year = year
    else:
        # If day is 1-19, billing period started last month
        if month == 1:
            period_start_month = 12
            period_start_year = year - 1
        else:
            period_start_month = month - 1
            period_start_year = year

        period_end_month = month
        period_end_year = year

    return {
        'key': f"{period_start_year}-{period_start_month:02d}~{period_end_year}-{period_end_month:02d}",
        'start_year': period_start_year,
        'start_month': period_start_month,
        'end_year': period_end_year,
        'end_month': period_end_month,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def billing_calculation(request, meter_name):
    """Calculate billing for past 12 billing periods (20/MM - 19/MM)"""
    try:
        tariff_type = request.GET.get('tariff_type', 'GENERAL').upper()
        periods = int(request.GET.get('periods', 12))

        if tariff_type not in ['GENERAL', 'TOU']:
            return Response({'error': 'Invalid tariff_type. Use GENERAL or TOU'}, status=400)

        # Get energy readings for past N billing periods (approximately 30 days each)
        # Include current incomplete day for real-time billing visibility
        now = timezone.now()
        start_date = now - timedelta(days=30 * periods)

        energy_readings = EnergyReading.objects.filter(
            meter_name=meter_name,
            timestamp__gte=start_date,
            timestamp__lte=now
        ).order_by('timestamp').values(
            'timestamp', 'import_active_energy'
        )

        if not energy_readings:
            return Response({'error': 'No energy data found for specified period'}, status=404)

        readings_list = list(energy_readings)

        # Group readings by billing period (20/MM - 19/MM)
        billing_periods = {}
        for reading in readings_list:
            timestamp = reading['timestamp']
            period_info = get_billing_period_key(timestamp)
            period_key = period_info['key']

            if period_key not in billing_periods:
                billing_periods[period_key] = {
                    'period': period_key,
                    'start_month': f"{period_info['start_year']}-{period_info['start_month']:02d}",
                    'end_month': f"{period_info['end_year']}-{period_info['end_month']:02d}",
                    'readings': [],
                }
            billing_periods[period_key]['readings'].append(reading)

        # Calculate billing for each period
        billing_data = []
        total_consumption = 0
        total_cost = 0

        for period_key in sorted(billing_periods.keys()):
            period_info = billing_periods[period_key]
            readings = period_info['readings']

            if not readings:
                continue

            # Use start month of billing period for AFA lookup
            start_year, start_month = map(int, period_info['start_month'].split('-'))
            billing_month = datetime(start_year, start_month, 1).date()

            if tariff_type == 'GENERAL':
                # For General Tariff: just use first and last readings
                first_reading = float(readings[0]['import_active_energy'] or 0)
                last_reading = float(readings[-1]['import_active_energy'] or 0)
                consumption = last_reading - first_reading

                if consumption < 0:
                    # Meter might have reset, skip this period
                    continue

                billing = calculate_general_tariff_billing(consumption, billing_month)

            else:  # TOU
                # For ToU: simplified calculation using boundary-based peak consumption
                billing = calculate_tou_billing(readings, billing_month)

            if billing:
                billing['period'] = period_key
                billing['start_month'] = period_info['start_month']
                billing['end_month'] = period_info['end_month']
                # Keep month fields for backward compatibility
                billing['month'] = period_key
                billing_data.append(billing)
                total_consumption += billing['consumption_kwh']
                total_cost += billing['total_amount_rm']

        avg_consumption = total_consumption / len(billing_data) if billing_data else 0
        avg_cost = total_cost / len(billing_data) if billing_data else 0

        return Response({
            'meter_name': meter_name,
            'tariff_type': tariff_type,
            'timezone': 'UTC+8',
            'billing_period_format': '20/MM - 19/MM',
            'billing_data': billing_data,
            'summary': {
                'total_consumption_kwh': round(total_consumption, 2),
                'total_cost_rm': round(total_cost, 2),
                'avg_monthly_consumption_kwh': round(avg_consumption, 2),
                'avg_monthly_cost_rm': round(avg_cost, 2),
                'periods_analyzed': len(billing_data),
            }
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'error': str(e)}, status=500)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def tariff_rates_list(request):
    """List all tariff rates or create new"""
    if request.method == 'GET':
        tariffs = TariffRate.objects.all().order_by('-effective_from')
        serializer = TariffRateSerializer(tariffs, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = TariffRateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def tariff_rates_active(request):
    """Get currently active tariff rates for both GENERAL and TOU"""
    today = timezone.now().date()
    tariffs = TariffRate.objects.filter(
        is_active=True,
        effective_from__lte=today
    ).order_by('tariff_type', '-effective_from').distinct('tariff_type')

    serializer = TariffRateSerializer(tariffs, many=True)
    return Response(serializer.data)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def tariff_rate_detail(request, pk):
    """Get or update a specific tariff rate"""
    try:
        tariff = TariffRate.objects.get(pk=pk)
    except TariffRate.DoesNotExist:
        return Response({'error': 'Tariff rate not found'}, status=404)

    if request.method == 'GET':
        serializer = TariffRateSerializer(tariff)
        return Response(serializer.data)
    elif request.method == 'PUT':
        serializer = TariffRateSerializer(tariff, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def fuel_adjustments_list(request):
    """List all fuel adjustments or create new"""
    if request.method == 'GET':
        afas = FuelAdjustment.objects.all().order_by('-effective_month')
        serializer = FuelAdjustmentSerializer(afas, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer = FuelAdjustmentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def fuel_adjustment_detail(request, pk):
    """Get or update a specific fuel adjustment"""
    try:
        afa = FuelAdjustment.objects.get(pk=pk)
    except FuelAdjustment.DoesNotExist:
        return Response({'error': 'Fuel adjustment not found'}, status=404)

    if request.method == 'GET':
        serializer = FuelAdjustmentSerializer(afa)
        return Response(serializer.data)
    elif request.method == 'PUT':
        serializer = FuelAdjustmentSerializer(afa, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)


def export_data(request, meter_name):
    """Export meter data as CSV or JSON.

    Parameters:
    - type: 'power' or 'energy' (default: power)
    - output: 'csv' or 'json' (default: csv)
    - days: Number of days to export (default: 7)
    - start_date: Custom start date (YYYY-MM-DD format)
    - end_date: Custom end date (YYYY-MM-DD format)
    - limit: Maximum number of records (default: 10000)

    If start_date and end_date are provided, they override the 'days' parameter.
    """
    try:
        data_type = request.GET.get('type', 'power')  # 'power' or 'energy'
        # Check both 'output' and 'format' parameters
        format_type = request.GET.get('output') or request.GET.get('format') or 'csv'
        format_type = format_type.lower()

        # Handle custom date range
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')

        if start_date_str and end_date_str:
            try:
                # Parse dates and make timezone-aware
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                # Set end_date to end of day
                end_date = end_date.replace(hour=23, minute=59, second=59)
                # Make timezone-aware (local timezone)
                start_time = LOCAL_TZ.localize(start_date)
                end_time = LOCAL_TZ.localize(end_date)
                period_desc = f"{start_date_str}_to_{end_date_str}"
            except ValueError:
                return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)
        else:
            days = int(request.GET.get('days', 7))
            end_time = timezone.now()
            start_time = end_time - timedelta(days=days)
            period_desc = f"{days}days"

        if data_type == 'power':
            # Use database-level timezone conversion for performance
            queryset = PowerReading.objects.filter(
                meter_name=meter_name,
                timestamp__gte=start_time,
                timestamp__lte=end_time
            ).extra(
                select={'local_timestamp': "to_char(timestamp AT TIME ZONE 'Asia/Kuala_Lumpur', 'YYYY-MM-DD HH24:MI:SS')"}
            ).order_by('timestamp')

            data = list(queryset.values(
                'local_timestamp', 'voltage', 'current', 'active_power',
                'apparent_power', 'reactive_power', 'power_factor', 'frequency'
            ))

            # Rename local_timestamp to timestamp for output
            for row in data:
                row['timestamp'] = row.pop('local_timestamp')

            columns = ['timestamp', 'voltage', 'current', 'active_power',
                       'apparent_power', 'reactive_power', 'power_factor', 'frequency']

        else:  # energy
            # Use database-level timezone conversion for performance
            queryset = EnergyReading.objects.filter(
                meter_name=meter_name,
                timestamp__gte=start_time,
                timestamp__lte=end_time
            ).extra(
                select={'local_timestamp': "to_char(timestamp AT TIME ZONE 'Asia/Kuala_Lumpur', 'YYYY-MM-DD HH24:MI:SS')"}
            ).order_by('timestamp')

            data = list(queryset.values(
                'local_timestamp', 'import_active_energy', 'export_active_energy',
                'import_reactive_energy', 'export_reactive_energy',
                'power_demand', 'maximum_power_demand'
            ))

            # Rename local_timestamp to timestamp for output
            for row in data:
                row['timestamp'] = row.pop('local_timestamp')

            columns = ['timestamp', 'import_active_energy', 'export_active_energy',
                       'import_reactive_energy', 'export_reactive_energy',
                       'power_demand', 'maximum_power_demand']

        if not data:
            return JsonResponse({'error': 'No data found for the specified period'}, status=404)

        if format_type == 'json':
            return JsonResponse({
                'meter_name': meter_name,
                'data_type': data_type,
                'period': period_desc,
                'record_count': len(data),
                'data': data
            })

        # Generate CSV
        df = pd.DataFrame(data, columns=columns)
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)

        response = HttpResponse(csv_buffer.getvalue(), content_type='text/csv')
        filename = f"{meter_name}_{data_type}_{period_desc}_{timezone.now().strftime('%Y%m%d')}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        return response

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
