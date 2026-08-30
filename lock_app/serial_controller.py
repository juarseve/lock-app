"""
Serial Communication Controller for ESP32 Microcontroller.
Handles physical lock triggering via PySerial on Linux Debian 13 (/dev/ttyUSB0)
or cross-platform USB serial ports.
"""

import logging
import time
import serial

logger = logging.getLogger(__name__)

def check_esp32_connection(port='/dev/ttyUSB0'):
    """
    Checks if ESP32 hardware device is physically connected and accessible.
    """
    try:
        with serial.Serial(port, baudrate=115200, timeout=0.5):
            return {
                'connected': True,
                'port': port,
                'message': f'ESP32 CONECTADO en {port}'
            }
    except Exception as e:
        return {
            'connected': False,
            'port': port,
            'message': f'ESP32 DESCONECTADO ({str(e)})'
        }


def send_unlock_command(command=b'OPEN\n', port='/dev/ttyUSB0', baudrate=115200, timeout=2.0):
    """
    Sends the physical unlock command (default: b'OPEN\\n') to the ESP32 via Serial.
    
    Args:
        command (bytes): Byte payload to send to ESP32. Default b'OPEN\\n'
        port (str): Path to serial device (e.g., '/dev/ttyUSB0'). Autodetected if None.
        baudrate (int): Serial baudrate (default 115200 for ESP32).
        timeout (float): Communication timeout in seconds.
        
    Returns:
        dict: {'success': bool, 'port': str, 'response': str, 'message': str}
    """
    target_port = port
    logger.info(f"[SerialController] Attempting to open serial connection on {target_port} at {baudrate} baud...")
    
    try:
        with serial.Serial(target_port, baudrate=baudrate, timeout=timeout) as ser:
            # Brief delay to allow hardware reset on connection if applicable
            time.sleep(0.1)
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Send command to ESP32
            bytes_written = ser.write(command)
            ser.flush()
            logger.info(f"[SerialController] Sent {bytes_written} bytes to ESP32: {command}")
            
            # Read confirmation response from ESP32 if available
            response_line = ""
            if ser.in_waiting > 0 or timeout > 0:
                try:
                    response_bytes = ser.readline()
                    response_line = response_bytes.decode('utf-8', errors='ignore').strip()
                    logger.info(f"[SerialController] ESP32 response: '{response_line}'")
                except Exception as read_err:
                    logger.warning(f"[SerialController] Could not read response line: {read_err}")
            
            return {
                'success': True,
                'port': target_port,
                'response': response_line or 'OK',
                'message': f"Comando '{command.decode().strip()}' enviado exitosamente a {target_port}."
            }

    except serial.SerialException as se:
        err_msg = f"Error de comunicación serial en puerto '{target_port}': {str(se)}"
        logger.error(f"[SerialController] {err_msg}")
        return {
            'success': False,
            'port': target_port,
            'response': None,
            'message': err_msg,
            'error_type': 'SerialException'
        }
    except FileNotFoundError:
        err_msg = f"Puerto serial '{target_port}' no encontrado. Verifica si el ESP32 está conectado a la PC."
        logger.error(f"[SerialController] {err_msg}")
        return {
            'success': False,
            'port': target_port,
            'response': None,
            'message': err_msg,
            'error_type': 'PortNotFound'
        }
    except PermissionError:
        err_msg = f"Permiso denegado al acceder a '{target_port}'. Ejecuta 'sudo usermod -a -G dialout $USER'."
        logger.error(f"[SerialController] {err_msg}")
        return {
            'success': False,
            'port': target_port,
            'response': None,
            'message': err_msg,
            'error_type': 'PermissionDenied'
        }
    except Exception as e:
        err_msg = f"Excepción inesperada al comunicar con ESP32: {str(e)}"
        logger.error(f"[SerialController] {err_msg}")
        return {
            'success': False,
            'port': target_port,
            'response': None,
            'message': err_msg,
            'error_type': 'UnexpectedError'
        }
