from time import sleep
import time
import struct
import socket
from typing import Union, Optional


class ModbusTCPClient:
    """Modbus TCP client for communication with Modbus TCP gateways.

    Modbus TCP frame format:
    - Transaction ID: 2 bytes
    - Protocol ID: 2 bytes (always 0x0000)
    - Length: 2 bytes (remaining bytes count)
    - Unit ID: 1 byte (slave address)
    - Function code: 1 byte
    - Data: variable
    """

    def __init__(self, ip: str, port: int = 502, timeout: float = 2.0):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.transaction_id = 0
        self._connected = False

    def connect(self) -> bool:
        """Establish TCP connection to the Modbus gateway."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.ip, self.port))
            self._connected = True
            print(f"Connected to Modbus TCP gateway at {self.ip}:{self.port}")
            return True
        except Exception as e:
            print(f"Failed to connect to {self.ip}:{self.port}: {e}")
            self.sock = None
            self._connected = False
            return False

    def close(self):
        """Close the TCP connection."""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
            self._connected = False

    @property
    def is_open(self) -> bool:
        """Check if connection is open."""
        return self._connected and self.sock is not None

    def read_registers(self, unit_id: int, function_code: int, start_address: int,
                       count: int, troubleshoot: int = 0) -> Optional[bytes]:
        """Send a Modbus TCP read request and get response.

        Args:
            unit_id: Slave/unit ID
            function_code: Modbus function code (3 or 4)
            start_address: Starting register address
            count: Number of registers to read
            troubleshoot: Enable debug output

        Returns:
            Raw data bytes from response, or None on failure
        """
        if not self.sock:
            return None

        try:
            # Clear any stale data in socket buffer before new request
            self._clear_socket_buffer()

            # Increment transaction ID
            self.transaction_id = (self.transaction_id + 1) % 65536

            # Build Modbus TCP frame
            # MBAP Header (7 bytes) + PDU
            pdu = bytes([
                function_code,
                (start_address >> 8) & 0xFF,
                start_address & 0xFF,
                (count >> 8) & 0xFF,
                count & 0xFF
            ])

            mbap_header = bytes([
                (self.transaction_id >> 8) & 0xFF,  # Transaction ID high
                self.transaction_id & 0xFF,          # Transaction ID low
                0x00, 0x00,                          # Protocol ID (always 0)
                0x00, len(pdu) + 1,                  # Length (PDU + unit ID)
                unit_id                              # Unit ID
            ])

            request = mbap_header + pdu

            if troubleshoot:
                hex_str = " ".join(f'{b:02x}' for b in request)
                print(f"Request (Modbus TCP): {hex_str}")

            # Send request
            self.sock.sendall(request)

            # Wait for response
            self.sock.settimeout(self.timeout)

            # Read MBAP header first (7 bytes)
            header = self._recv_exact(7)
            if not header or len(header) < 7:
                if troubleshoot:
                    print(f"Failed to receive MBAP header, got {len(header) if header else 0} bytes")
                return None

            # Parse header
            recv_trans_id = (header[0] << 8) | header[1]
            protocol_id = (header[2] << 8) | header[3]
            length = (header[4] << 8) | header[5]
            recv_unit_id = header[6]

            if troubleshoot:
                print(f"Response header: trans_id={recv_trans_id}, proto={protocol_id}, len={length}, unit={recv_unit_id}")

            # Verify transaction ID matches (critical for correct response matching)
            if recv_trans_id != self.transaction_id:
                if troubleshoot:
                    print(f"Transaction ID mismatch: expected {self.transaction_id}, got {recv_trans_id}")
                # Try to clear any remaining data and return None
                self._clear_socket_buffer()
                return None

            # Read the rest of the response
            remaining = length - 1  # -1 because unit_id is already read
            if remaining <= 0:
                if troubleshoot:
                    print("Invalid response length")
                return None

            pdu_response = self._recv_exact(remaining)
            if not pdu_response or len(pdu_response) < remaining:
                if troubleshoot:
                    print(f"Failed to receive PDU, got {len(pdu_response) if pdu_response else 0} bytes, expected {remaining}")
                return None

            if troubleshoot:
                hex_str = " ".join(f'{b:02x}' for b in (header + pdu_response))
                print(f"Response (Modbus TCP): {hex_str}")

            # Check for error response
            if pdu_response[0] & 0x80:
                error_code = pdu_response[1] if len(pdu_response) > 1 else 0
                print(f"Modbus error response: exception code {error_code}")
                return None

            # Verify function code matches
            if pdu_response[0] != function_code:
                if troubleshoot:
                    print(f"Function code mismatch: expected {function_code}, got {pdu_response[0]}")
                return None

            # Return data bytes (skip function code and byte count)
            if len(pdu_response) > 2:
                byte_count = pdu_response[1]
                data = pdu_response[2:2+byte_count]
                return bytes(data)

            return None

        except socket.timeout:
            if troubleshoot:
                print("Socket timeout waiting for response")
            self.close()  # Close zombie socket so reconnection triggers
            return None
        except Exception as e:
            print(f"Modbus TCP error: {e}")
            self.close()  # Close zombie socket so reconnection triggers
            return None

    def _recv_exact(self, size: int) -> Optional[bytes]:
        """Receive exactly 'size' bytes from socket."""
        if not self.sock:
            return None

        data = bytearray()
        start_time = time.time()

        while len(data) < size:
            if time.time() - start_time > self.timeout:
                break
            try:
                chunk = self.sock.recv(size - len(data))
                if not chunk:
                    break
                data.extend(chunk)
            except socket.timeout:
                break
            except Exception:
                break

        return bytes(data) if data else None

    def _clear_socket_buffer(self):
        """Clear any pending data in socket buffer."""
        if not self.sock:
            return

        try:
            self.sock.setblocking(False)
            while True:
                try:
                    data = self.sock.recv(1024)
                    if not data:
                        break
                except BlockingIOError:
                    break
                except:
                    break
            self.sock.setblocking(True)
            self.sock.settimeout(self.timeout)
        except:
            pass


def parse_register_data(data: bytes, datatype: str, endian: int, troubleshoot: int = 0) -> Union[float, int]:
    """Parse register data according to data type and endianness.

    Args:
        data: Raw bytes from Modbus response
        datatype: 'int', 'sint', or 'float'
        endian: Byte order (e.g., 1234, 2143, 3412, 4321)
        troubleshoot: Enable debug output

    Returns:
        Parsed value or -999 on error
    """
    if not data:
        return -999

    try:
        byte_count = len(data)

        if troubleshoot:
            hex_str = " ".join(f'{b:02x}' for b in data)
            print(f"Parsing data: {hex_str}, type={datatype}, endian={endian}")

        # Reorder bytes according to endianness
        endian_str = str(endian)
        reordered = bytearray(byte_count)

        if byte_count == 2:
            if len(endian_str) >= 2:
                endian_digits = [int(d)-1 for d in endian_str[:2]]
            else:
                endian_digits = [0, 1]
        elif byte_count == 4:
            if len(endian_str) >= 4:
                endian_digits = [int(d)-1 for d in endian_str[:4]]
            else:
                endian_digits = [0, 1, 2, 3]
        elif byte_count == 8:
            if len(endian_str) >= 8:
                endian_digits = [int(d)-1 for d in endian_str[:8]]
            else:
                endian_digits = [0, 1, 2, 3, 4, 5, 6, 7]
        else:
            endian_digits = list(range(byte_count))

        for i, pos in enumerate(endian_digits):
            if i < byte_count and pos < byte_count:
                reordered[i] = data[pos]

        # Convert to specified data type
        if datatype == 'float':
            if byte_count >= 4:
                result = struct.unpack('>f', reordered[:4])[0]
                if troubleshoot:
                    print(f"Parsed float: {result}")
                return result
            else:
                print("Error: Float type requires at least 4 bytes")
                return -999
        elif datatype == 'int':
            value = 0
            for byte in reordered:
                value = (value << 8) | byte
            if troubleshoot:
                print(f"Parsed int: {value}")
            return value
        elif datatype == 'sint':
            if byte_count == 2:
                result = struct.unpack('>h', reordered[:2])[0]
            elif byte_count >= 4:
                result = struct.unpack('>i', reordered[:4])[0]
            elif byte_count == 1:
                result = struct.unpack('>b', reordered[:1])[0]
            else:
                print(f"Unsupported byte count for sint: {byte_count}")
                return -999
            if troubleshoot:
                print(f"Parsed sint: {result}")
            return result

        return -999

    except Exception as e:
        print(f"Data parsing error: {e}")
        return -999
