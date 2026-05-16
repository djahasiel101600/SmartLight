import serial
import time
import threading

class DimmerController:
    def __init__(self, port='/dev/ttyACM0', baud=9600):
        try:
            # On Linux/Raspberry Pi, exclusive=True prevents another process
            # (e.g., serial monitor) from opening the same port concurrently.
            self.ser = serial.Serial(port, baud, timeout=0.5, exclusive=True)
        except TypeError:
            # Fallback for platforms/pyserial builds without 'exclusive'.
            self.ser = serial.Serial(port, baud, timeout=0.5)
        self._io_lock = threading.Lock()
        time.sleep(2)  # Wait for Arduino reset
        self.check_ready()
    
    def check_ready(self):
        with self._io_lock:
            response = self._readline_clean()
        if 'READY' in response:
            print(f"Connected: {response}")
            # Flush any remaining startup lines so they don't corrupt the first command response
            time.sleep(0.1)
            with self._io_lock:
                self.ser.reset_input_buffer()
            return True
        return False

    def _readline_clean(self):
        """Read one line, decoding safely and trimming whitespace."""
        return self.ser.readline().decode(errors='replace').strip()

    def _request_line(self, command, expected_prefixes=None, max_reads=8):
        """Send one command and scan subsequent lines for expected prefixes.

        Returns the first matching line, or the last non-empty line if no
        expected prefix is supplied/found.
        """
        if expected_prefixes is None:
            expected_prefixes = ()
        elif isinstance(expected_prefixes, str):
            expected_prefixes = (expected_prefixes,)

        cmd = f"{command}\n"
        self.ser.reset_input_buffer()
        self.ser.write(cmd.encode())

        last_non_empty = ""
        for _ in range(max_reads):
            line = self._readline_clean()
            if not line:
                continue
            last_non_empty = line
            if not expected_prefixes:
                return line
            if any(line.startswith(prefix) for prefix in expected_prefixes):
                return line
        return last_non_empty
    
    def send_command(self, behavior, brightness):
        """Send command and return response"""
        with self._io_lock:
            response = self._request_line(
                f"{behavior}:{brightness}",
                expected_prefixes=("OK:", "ERROR:", "STATUS:"),
            )
        return response
    
    def get_status(self):
        """Get current status"""
        with self._io_lock:
            return self._request_line("STATUS", expected_prefixes="REPORT:")
    
    def ping(self):
        """Check if Arduino is alive"""
        with self._io_lock:
            response = self._request_line("PING", expected_prefixes="RESPONSE:PONG")
        return 'PONG' in response

    def send_raw_command(self, command, expected_prefix=None, retries=2):
        """Send a raw command and return the response.

        If expected_prefix is provided, retries until a matching line arrives
        (or retries are exhausted).
        """
        with self._io_lock:
            response = ""
            for _ in range(max(1, retries)):
                response = self._request_line(command, expected_prefixes=expected_prefix)
                if not expected_prefix or response.startswith(expected_prefix):
                    return response
            return response

# Usage example
# dimmer = DimmerController()
# dimmer.send_command("idle", 30)
# dimmer.send_command("reading_book", 70)
# print(dimmer.get_status())