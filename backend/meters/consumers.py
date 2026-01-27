import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from datetime import datetime
import pytz


LOCAL_TZ = pytz.timezone('Asia/Kuala_Lumpur')


class ReadingsConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for frontend clients to receive real-time data."""

    async def connect(self):
        self.group_name = 'readings'

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

        # Send initial data on connection
        initial_data = await self.get_full_update()
        await self.send(text_data=json.dumps(initial_data))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        data = json.loads(text_data)

        # Handle heartbeat ping
        if data.get('type') == 'ping':
            await self.send(text_data=json.dumps({
                'type': 'pong',
                'timestamp': data.get('timestamp'),
                'server_time': datetime.now(pytz.UTC).isoformat()
            }))
            return

        if data.get('type') == 'request_update':
            full_data = await self.get_full_update()
            await self.send(text_data=json.dumps(full_data))
        elif data.get('type') == 'request_timeseries':
            meter_name = data.get('meter_name')
            if meter_name:
                timeseries = await self.get_initial_timeseries(meter_name)
                await self.send(text_data=json.dumps({
                    'type': 'initial_timeseries',
                    'meter_name': meter_name,
                    'data': timeseries
                }))

    @database_sync_to_async
    def get_full_update(self):
        from .views import get_readings_summary_sync, get_realtime_data_sync, get_timeseries_point_sync
        summary = get_readings_summary_sync()

        realtime_data = {}
        timeseries_points = {}

        for meter in summary:
            name = meter['meter_name']
            rt_data = get_realtime_data_sync(name)
            if rt_data:
                realtime_data[name] = rt_data

            ts_point = get_timeseries_point_sync(name)
            if ts_point:
                timeseries_points[name] = ts_point

        return {
            'type': 'full_update',
            'summary': summary,
            'realtime': realtime_data,
            'timeseries_point': timeseries_points
        }

    @database_sync_to_async
    def get_initial_timeseries(self, meter_name):
        from .models import PowerReading
        from django.utils import timezone
        from datetime import timedelta

        start_time = timezone.now() - timedelta(minutes=15)
        readings = PowerReading.objects.filter(
            meter_name=meter_name,
            timestamp__gte=start_time
        ).order_by('timestamp').values(
            'timestamp', 'voltage', 'current', 'active_power', 'power_factor', 'frequency'
        )

        return [
            {
                'timestamp': r['timestamp'].isoformat(),
                'voltage': r['voltage'] or 0,
                'current': r['current'] or 0,
                'active_power': r['active_power'] or 0,
                'power_factor': r['power_factor'] or 0,
                'frequency': r['frequency'] or 0
            }
            for r in readings
        ]

    async def readings_update(self, event):
        await self.send(text_data=json.dumps(event['data']))


class DeviceConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for IoT devices to stream real-time data directly."""

    async def connect(self):
        self.device_group = 'devices'
        self.readings_group = 'readings'
        self.meter_name = None

        await self.channel_layer.group_add(
            self.device_group,
            self.channel_name
        )
        await self.accept()
        print(f"Device connected: {self.channel_name}")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.device_group,
            self.channel_name
        )
        print(f"Device disconnected: {self.channel_name}, meter: {self.meter_name}")

    async def receive(self, text_data):
        """
        Handle incoming data from IoT device.
        Expected format:
        {
            "type": "meter_reading",
            "meter_name": "Main",
            "timestamp": 1640995200,  # Unix timestamp (optional, uses server time if not provided)
            "readings": {
                "voltage": 230.5,
                "current": 10.2,
                "active_power": 2351.0,
                "apparent_power": 2400.0,
                "reactive_power": 250.0,
                "power_factor": 0.98,
                "frequency": 50.0,
                "import_active_energy": 12345.67,
                "export_active_energy": 0
            }
        }
        """
        try:
            data = json.loads(text_data)

            # Handle heartbeat ping
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': data.get('timestamp'),
                    'server_time': datetime.now(pytz.UTC).isoformat()
                }))
                return

            if data.get('type') == 'meter_reading':
                await self.handle_meter_reading(data)
            elif data.get('type') == 'register':
                # Device registration
                self.meter_name = data.get('meter_name')
                await self.send(text_data=json.dumps({
                    'type': 'registered',
                    'meter_name': self.meter_name,
                    'status': 'ok'
                }))
        except json.JSONDecodeError as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Invalid JSON: {str(e)}'
            }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))

    async def handle_meter_reading(self, data):
        """Process and broadcast meter reading from IoT device."""
        meter_name = data.get('meter_name') or self.meter_name
        if not meter_name:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'meter_name is required'
            }))
            return

        readings = data.get('readings', {})

        # Get timestamp
        timestamp = data.get('timestamp')
        if timestamp:
            if isinstance(timestamp, (int, float)):
                dt = datetime.fromtimestamp(timestamp, tz=pytz.UTC)
            else:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        else:
            dt = datetime.now(pytz.UTC)

        local_time = dt.astimezone(LOCAL_TZ)

        # Build realtime data
        realtime_data = {
            'meter_name': meter_name,
            'timestamp': dt.isoformat(),
            'local_time': local_time.isoformat(),
            'timezone': 'UTC+8',
            'voltage': readings.get('voltage') or readings.get('Voltage'),
            'current': readings.get('current') or readings.get('Current'),
            'active_power': readings.get('active_power') or readings.get('Active Power') or 0,
            'apparent_power': readings.get('apparent_power') or readings.get('Apparent Power') or 0,
            'reactive_power': readings.get('reactive_power') or readings.get('Reactive Power') or 0,
            'power_factor': readings.get('power_factor') or readings.get('Power Factor'),
            'frequency': readings.get('frequency') or readings.get('Frequency'),
            'import_active_energy': readings.get('import_active_energy') or readings.get('Import Active Energy'),
            'export_active_energy': readings.get('export_active_energy') or readings.get('Export Active Energy'),
            'power_demand': readings.get('power_demand') or readings.get('Power Demand'),
        }

        # Build timeseries point
        timeseries_point = {
            'meter_name': meter_name,
            'timestamp': dt.isoformat(),
            'active_power': realtime_data['active_power'],
            'voltage': realtime_data['voltage'] or 0,
            'current': realtime_data['current'] or 0,
            'power_factor': realtime_data['power_factor'] or 0,
            'frequency': realtime_data['frequency'] or 0
        }

        # Build summary entry
        summary_entry = {
            'meter_name': meter_name,
            'status': 'online',
            'latest_power_timestamp': dt.isoformat(),
            'voltage': realtime_data['voltage'],
            'current': realtime_data['current'],
            'active_power': realtime_data['active_power'],
            'frequency': realtime_data['frequency'],
            'import_active_energy': realtime_data['import_active_energy'],
            'export_active_energy': realtime_data['export_active_energy'],
            'power_demand': realtime_data['power_demand'],
        }

        # Broadcast to all frontend clients
        await self.channel_layer.group_send(
            self.readings_group,
            {
                'type': 'readings_update',
                'data': {
                    'type': 'full_update',
                    'summary': [summary_entry],
                    'realtime': {meter_name: realtime_data},
                    'timeseries_point': {meter_name: timeseries_point}
                }
            }
        )

        # Acknowledge receipt
        await self.send(text_data=json.dumps({
            'type': 'ack',
            'meter_name': meter_name,
            'timestamp': dt.isoformat()
        }))
