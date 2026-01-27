import json
import asyncio
import time
import sys
from functools import lru_cache
from api_client import APIClient
from typing import Dict, List, Any, Optional
from datetime import datetime
from modbus import ModbusTCPClient, parse_register_data

# Define variables
setting: Dict[str, Any] = {}
logged: Dict[str, Any] = {}
status: Dict[str, Any] = {'error': 0}
arrayMeterName: List[str] = []
api_client = APIClient()

# Load settings from JSON file
try:
    with open('setting.json', 'r') as f:
        setting = json.load(f)
except FileNotFoundError:
    print("Error: setting.json file not found. Please ensure the configuration file exists.")
    raise
except json.JSONDecodeError as e:
    print(f"Error: Invalid JSON in setting.json: {e}")
    raise

client: Optional[ModbusTCPClient] = None
logger_id = setting['Logger_ID']
device_ip = setting['Device_IP']
device_port = setting.get('Device_Port', 502)
debug = setting.get('debug', False)
troubleshoot = setting.get('Troubleshoot', 0)

# Parameters that should only be stored every minute (energy and demand)
MINUTE_INTERVAL_PARAMS = {
    'Import Active Energy',
    'Export Active Energy',
    'Import Reactive Energy',
    'Export Reactive Energy',
    'Power Demand',
    'Maximum Power Demand',
    'Current Demand',
    'Maximum Current Demand',
}

# Track last minute storage time
last_minute_storage = 0

# Validation ranges for single-phase system (Malaysia 230V/63A)
VALIDATION_RANGES = {
    'Voltage': (100, 300),          # Valid voltage range
    'Current': (0, 100),            # Valid current range
    'Frequency': (45, 55),          # Valid frequency range (Malaysia: 50Hz)
    'Power Factor': (-1.5, 1.5),    # Valid power factor range
    'Active Power': (-20000, 20000), # Valid power range for single-phase
    'Apparent Power': (0, 20000),
    'Reactive Power': (-20000, 20000),
}


def group_contiguous_registers(paramlist: List[str], paraminfo: Dict[str, Any],
                                max_gap: int = 2) -> List[Dict]:
    """Group parameters with contiguous register addresses for batch reading.

    Args:
        paramlist: List of parameter names
        paraminfo: Dict mapping param names to their info (id, size, type, endian, mul)
        max_gap: Maximum gap between registers to still include in same group

    Returns:
        List of groups: [{start_addr, count, params: [{name, offset, size, ...}]}]
    """
    if not paramlist:
        return []

    # Build list of (address, size, name, info) and sort by address
    params_with_addr = []
    for name in paramlist:
        info = paraminfo.get(name)
        if info and 'id' in info:
            params_with_addr.append({
                'name': name,
                'address': info['id'],
                'size': info.get('size', 2),
                'type': info.get('type', 'float'),
                'endian': info.get('endian', 1234),
                'mul': info.get('mul', 1)
            })

    if not params_with_addr:
        return []

    # Sort by register address
    params_with_addr.sort(key=lambda x: x['address'])

    # Group contiguous registers
    groups = []
    current_group = None

    for param in params_with_addr:
        addr = param['address']
        size = param['size']

        if current_group is None:
            # Start new group
            current_group = {
                'start_addr': addr,
                'end_addr': addr + size,
                'params': [param]
            }
        elif addr <= current_group['end_addr'] + max_gap:
            # Add to current group (contiguous or within gap tolerance)
            current_group['params'].append(param)
            current_group['end_addr'] = max(current_group['end_addr'], addr + size)
        else:
            # Start new group
            groups.append(current_group)
            current_group = {
                'start_addr': addr,
                'end_addr': addr + size,
                'params': [param]
            }

    # Don't forget the last group
    if current_group:
        groups.append(current_group)

    # Calculate count and offsets for each group
    for group in groups:
        group['count'] = group['end_addr'] - group['start_addr']
        for param in group['params']:
            param['offset'] = param['address'] - group['start_addr']

    return groups


def validate_readings(readings: Dict[str, float]) -> tuple:
    """Validate readings are within expected physical ranges.

    Returns:
        (is_valid, error_message) tuple
    """
    for param, (min_val, max_val) in VALIDATION_RANGES.items():
        if param in readings:
            value = readings[param]
            if value is not None and (value < min_val or value > max_val):
                return False, f"{param}={value:.2f} out of range [{min_val}, {max_val}]"
    return True, None


@lru_cache(maxsize=1000)
def cache_meter_value(meter_id: str, param: str, value: float, timestamp: float) -> float:
    """Cache meter readings with TTL."""
    return value


async def read_register_group(client: ModbusTCPClient, meter_id: int, function_code: int,
                               group: Dict, troubleshoot: int = 0) -> Dict[str, Optional[float]]:
    """Read a group of contiguous registers in one Modbus transaction.

    Args:
        client: ModbusTCPClient instance
        meter_id: Slave/unit ID
        function_code: Modbus function code
        group: Group dict with start_addr, count, and params list
        troubleshoot: Debug output level

    Returns:
        Dict mapping param_name -> parsed value (or None on failure)
    """
    results = {}

    try:
        # Read all registers in the group at once
        data = client.read_registers(
            unit_id=meter_id,
            function_code=function_code,
            start_address=group['start_addr'],
            count=group['count'],
            troubleshoot=troubleshoot
        )

        if data is None:
            # Return None for all params in group
            for param in group['params']:
                results[param['name']] = None
            return results

        # Parse each parameter from the batch response
        for param in group['params']:
            try:
                # Extract bytes for this parameter (2 bytes per register)
                offset_bytes = param['offset'] * 2
                size_bytes = param['size'] * 2
                param_data = data[offset_bytes:offset_bytes + size_bytes]

                if len(param_data) < size_bytes:
                    results[param['name']] = None
                    continue

                # Parse the data
                value = parse_register_data(
                    data=param_data,
                    datatype=param['type'],
                    endian=param['endian'],
                    troubleshoot=troubleshoot
                )

                if value == -999:
                    results[param['name']] = None
                    continue

                # Apply multiplier
                multiplier = param.get('mul', 1)
                results[param['name']] = round(float(value) * multiplier, 3)

            except Exception as e:
                if troubleshoot:
                    print(f"Error parsing param {param['name']}: {e}")
                results[param['name']] = None

        return results

    except Exception as e:
        print(f"Error reading register group: {e}")
        for param in group['params']:
            results[param['name']] = None
        return results


async def read_parameter(client: ModbusTCPClient, meter_id: int, function_code: int,
                         param: Dict[str, Any], troubleshoot: int = 0) -> Optional[float]:
    """Read a single parameter from a meter.

    Args:
        client: ModbusTCPClient instance
        meter_id: Slave/unit ID
        function_code: Modbus function code
        param: Parameter info dict with 'id', 'size', 'type', 'endian', 'mul'
        troubleshoot: Debug output level

    Returns:
        Parsed value or None on failure
    """
    try:
        # Read registers
        data = client.read_registers(
            unit_id=meter_id,
            function_code=function_code,
            start_address=param['id'],
            count=param['size'],
            troubleshoot=troubleshoot
        )

        if data is None:
            return None

        # Parse the data
        value = parse_register_data(
            data=data,
            datatype=param['type'],
            endian=param['endian'],
            troubleshoot=troubleshoot
        )

        if value == -999:
            return None

        # Apply multiplier
        multiplier = param.get('mul', 1)
        result = float(value) * multiplier

        return round(result, 3)

    except Exception as e:
        print(f"Error reading parameter: {e}")
        return None


async def read_meter(meter: str, current_time: float, read_minute_params: bool = False) -> Dict[str, float]:
    """Read parameters from a meter and return the readings.

    Args:
        meter: Meter name
        current_time: Current timestamp
        read_minute_params: If True, also read energy/demand parameters
    """
    global client

    currentMeter = logged[meter]
    readings = {}

    try:
        start_time = time.time()
        success_count = 0
        fail_count = 0

        # Filter params based on whether we're reading minute-interval data
        active_params = [
            p for p in currentMeter['paramlist']
            if p not in MINUTE_INTERVAL_PARAMS or read_minute_params
        ]

        # Use cached register groups or build them
        if 'register_groups' in currentMeter:
            # Filter cached groups to only include active params
            groups = []
            for group in currentMeter['register_groups']:
                filtered_params = [p for p in group['params'] if p['name'] in active_params]
                if filtered_params:
                    groups.append({
                        'start_addr': group['start_addr'],
                        'count': group['count'],
                        'params': filtered_params
                    })
        else:
            # Build groups on the fly (fallback)
            groups = group_contiguous_registers(active_params, currentMeter['paraminfo'])

        # Read each register group with retry
        for group in groups:
            group_values = None
            for attempt in range(2):
                group_values = await read_register_group(
                    client=client,
                    meter_id=int(currentMeter['id']),
                    function_code=currentMeter['functionCode'],
                    group=group,
                    troubleshoot=troubleshoot
                )

                # Check if we got at least some valid values
                if group_values and any(v is not None for v in group_values.values()):
                    break

                if attempt < 1:
                    await asyncio.sleep(0.02)  # 20ms retry delay

            # Process results from this group
            if group_values:
                for param_name, value in group_values.items():
                    if value is not None:
                        readings[param_name] = value
                        currentMeter['paraminfo'][param_name]['value'] = value
                        success_count += 1
                    else:
                        fail_count += 1

            # Minimal delay between groups
            await asyncio.sleep(0.005)  # 5ms between groups

        latency = time.time() - start_time
        timestamp = datetime.now().strftime('%H:%M:%S')
        group_count = len(groups)

        if read_minute_params:
            print(f"[{timestamp}] {meter}: {success_count}/{success_count+fail_count} read, {latency*1000:.0f}ms ({group_count} groups, full read)")
        else:
            print(f"[{timestamp}] {meter}: {success_count}/{success_count+fail_count} read, {latency*1000:.0f}ms ({group_count} groups)")

        logged[meter]['latest_readings'].update(readings)
        logged[meter]['latest_time'] = current_time

        return readings

    except Exception as e:
        print(f"Error reading meter {meter}: {str(e)}")
        import traceback
        traceback.print_exc()
        return {}


async def modbus_logger() -> None:
    """Main modbus logging function that reads data from meters and stores immediately."""
    global setting, logged, client, status, arrayMeterName, last_minute_storage

    print("Modbus Logger running (Modbus TCP mode)")

    try:
        with open(setting["meter_params"], 'r') as m:
            meterparamjson = json.load(m)
    except FileNotFoundError:
        print(f"Error: Meter parameters file '{setting['meter_params']}' not found.")
        raise
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in meter parameters file: {e}")
        raise

    meterlist = setting["meterlist"]

    # Initialize logging structure and database
    logged = {}
    arrayMeterName = []

    print("Initializing meters:")
    for meter in meterlist:
        mname = meter["name"]
        meter_id = int(meter["id"])
        arrayMeterName.append(mname)
        logged[mname] = {
            "id": meter_id,
            "name": meter["name"],
            "model": meter["model"],
            "functionCode": meterparamjson[meter["model"]]["functionCode"],
            "paramlist": [],
            "paraminfo": {},
            "latest_readings": {},
            "latest_time": 0,
        }
        print(f"  Meter: {mname}, ID: {meter_id}, Model: {meter['model']}")

        # Meter info will be managed through Django admin interface

        for param in meter["paramlist"]:
            logged[mname]["paramlist"].append(param)
            temp = meterparamjson[meter["model"]][param].copy()
            temp.pop('description', None)
            logged[mname]["paraminfo"][param] = temp
            logged[mname]["paraminfo"][param]["value"] = -999

        # Pre-calculate register groups for batch reading
        logged[mname]["register_groups"] = group_contiguous_registers(
            logged[mname]["paramlist"],
            logged[mname]["paraminfo"]
        )
        group_count = len(logged[mname]["register_groups"])
        param_count = len(logged[mname]["paramlist"])
        print(f"    -> {param_count} params grouped into {group_count} batch reads")

    print(f"\nStarting meter reading loop...")
    print(f"Target: {device_ip}:{device_port}")

    while True:
        try:
            # Establish TCP connection if not connected
            if not client or not client.is_open:
                client = ModbusTCPClient(device_ip, device_port, timeout=0.5)
                if not client.connect():
                    print(f"Connection failed, retrying in 5 seconds...")
                    await asyncio.sleep(5)
                    continue

            current_time = time.time()
            unix_time = int(current_time)

            # Check if we should read and store minute-interval data
            current_minute = unix_time - (unix_time % 60)
            read_minute_data = current_minute > last_minute_storage

            # Read meters and store based on parameter type
            for meter_name in arrayMeterName:
                try:
                    # Read parameters (only instant, or all if at minute mark)
                    readings = await read_meter(meter_name, current_time, read_minute_params=read_minute_data)

                    if readings:
                        # Validate readings before storing
                        is_valid, error_msg = validate_readings(readings)
                        if not is_valid:
                            print(f"[WARNING] Invalid readings from {meter_name}: {error_msg} - skipping")
                            continue

                        # Separate instant and minute-interval readings
                        instant_readings = {k: v for k, v in readings.items()
                                          if k not in MINUTE_INTERVAL_PARAMS}
                        minute_readings = {k: v for k, v in readings.items()
                                         if k in MINUTE_INTERVAL_PARAMS}

                        # Store instant readings every read
                        if instant_readings:
                            success = api_client.send_meter_reading(meter_name, unix_time, instant_readings)
                            if not success:
                                print(f"Failed to send instant readings for {meter_name}")

                        # Store energy/demand readings only at minute marks
                        if minute_readings and read_minute_data:
                            success = api_client.send_meter_reading(meter_name, current_minute, minute_readings)
                            if not success:
                                print(f"Failed to send minute readings for {meter_name}")

                except Exception as meter_error:
                    print(f"Error reading meter {meter_name}: {str(meter_error)}")
                    continue

                # Delay between meters for reliable communication
                await asyncio.sleep(0.2)  # 200ms delay between meters

            # Update last minute storage time
            if read_minute_data:
                last_minute_storage = current_minute

            # Delay before next read cycle for reliable data
            await asyncio.sleep(0.5)  # Increased from 100ms to 500ms

        except Exception as e:
            print(f"Modbus Logger Error: {str(e)}")
            if client and client.is_open:
                client.close()
            await asyncio.sleep(5)
            continue


async def health_check_worker() -> None:
    """Periodically check API health and log status."""
    while True:
        try:
            if api_client.health_check():
                print(f"API health check passed at {datetime.now()}")
            else:
                print(f"API health check failed at {datetime.now()}")
            await asyncio.sleep(300)  # Check every 5 minutes
        except Exception as e:
            print(f"Health check error: {str(e)}")
            await asyncio.sleep(60)


async def main() -> None:
    """Main application entry point."""
    tasks = [
        modbus_logger(),
        health_check_worker()
    ]

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    print(f"=" * 60)
    print(f"Home Logger - Modbus TCP Mode")
    print(f"=" * 60)
    print(f"Device: {device_ip}:{device_port}")
    print(f"Logger ID: {logger_id}")
    print(f"Troubleshoot: {troubleshoot}")
    print(f"=" * 60)
    print()

    while True:
        try:
            asyncio.run(main())
            print("Main job is done")
            break
        except KeyboardInterrupt:
            print("\nApplication stopped by user")
            break
        except Exception as e:
            print(f"Fatal error: {str(e)}")
            status['error'] += 1

            if status.get('error', 0) > 10:
                print("Too many errors. Exiting...")
                if client and client.is_open:
                    client.close()
                sys.exit(1)
            else:
                print(f"Error count: {status['error']}/10. Restarting in 5 seconds...")
                time.sleep(5)
                continue
        finally:
            if client and client.is_open:
                client.close()
