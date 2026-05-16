import serial
import time
import threading

class DimmerController:
    def __init__(self, port='/dev/ttyACM0', baud=9600):
        self.ser = serial.Serial(port, baud, timeout=0.15)
        self._io_lock = threading.Lock()
        time.sleep(2)  # Wait for Arduino reset
        self.check_ready()
    
    def check_ready(self):
        with self._io_lock:
            response = self.ser.readline().decode().strip()
        if 'READY' in response:
            print(f"Connected: {response}")
            # Flush any remaining startup lines so they don't corrupt the first command response
            time.sleep(0.1)
            with self._io_lock:
                self.ser.reset_input_buffer()
            return True
        return False
    
    def send_command(self, behavior, brightness):
        """Send command and return response"""
        cmd = f"{behavior}:{brightness}\n"
        with self._io_lock:
            self.ser.write(cmd.encode())
            response = self.ser.readline().decode().strip()
        return response
    
    def get_status(self):
        """Get current status"""
        with self._io_lock:
            self.ser.write(b"STATUS\n")
            return self.ser.readline().decode().strip()
    
    def ping(self):
        """Check if Arduino is alive"""
        with self._io_lock:
            self.ser.write(b"PING\n")
            response = self.ser.readline().decode().strip()
        return 'PONG' in response

    def send_raw_command(self, command, expected_prefix=None, retries=2):
        """Send a raw command and return the response.

        If expected_prefix is provided, retries until a matching line arrives
        (or retries are exhausted).
        """
        cmd = f"{command}\n"
        with self._io_lock:
            for _ in range(max(1, retries)):
                self.ser.write(cmd.encode())
                response = self.ser.readline().decode().strip()
                if not expected_prefix or response.startswith(expected_prefix):
                    return response
            return response

# Usage example
# dimmer = DimmerController()
# dimmer.send_command("idle", 30)
# dimmer.send_command("reading_book", 70)
# print(dimmer.get_status())