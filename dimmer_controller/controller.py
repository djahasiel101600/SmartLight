import serial
import time

class DimmerController:
    def __init__(self, port='/dev/ttyACM0', baud=9600):
        self.ser = serial.Serial(port, baud, timeout=0.15)
        time.sleep(2)  # Wait for Arduino reset
        self.check_ready()
    
    def check_ready(self):
        response = self.ser.readline().decode().strip()
        if 'READY' in response:
            print(f"Connected: {response}")
            # Flush any remaining startup lines so they don't corrupt the first command response
            time.sleep(0.1)
            self.ser.reset_input_buffer()
            return True
        return False
    
    def send_command(self, behavior, brightness):
        """Send command and return response"""
        cmd = f"{behavior}:{brightness}\n"
        self.ser.write(cmd.encode())
        response = self.ser.readline().decode().strip()
        return response
    
    def get_status(self):
        """Get current status"""
        self.ser.write(b"STATUS\n")
        return self.ser.readline().decode().strip()
    
    def ping(self):
        """Check if Arduino is alive"""
        self.ser.write(b"PING\n")
        response = self.ser.readline().decode().strip()
        return 'PONG' in response

    def send_raw_command(self, command):
        """Send a raw command and return the response"""
        cmd = f"{command}\n"
        self.ser.write(cmd.encode())
        response = self.ser.readline().decode().strip()
        return response

# Usage example
# dimmer = DimmerController()
# dimmer.send_command("idle", 30)
# dimmer.send_command("reading_book", 70)
# print(dimmer.get_status())