# from qbdevices import *
# from qbdevicescopy import *
# from serial_com_test import *
from qbrobotics_serial_utils import *
from qbrobotics_commands import *
import time

print("\n###############################################")
print("### Python libraries for qbrobotics devices ###")
print("###############################################\n")


# COMMANDS

# CMD_PING               = 0   # 0   --> CMD_PING
# CMD_GET_INFO           = 6   # 6   --> CMD_GET_INFO, NEED PARAMS
# CMD_BOOTLOADER         = 9   # 9   --> CMD_BOOTLOADER
# CMD_ACTIVATE           = 128 # 128 --> CMD_ACTIVATE, NEED PARAMS
# CMD_GET_ACTIVATE       = 129 # 129 --> CMD_GET_ACTIVATE
# CMD_SET_INPUTS         = 130 # 130 --> CMD_SET_INPUTS, NEED PARAMS
# CMD_GET_INPUTS         = 131 # 131 --> CMD_GET_INPUTS
# CMD_GET_MEASUREMENTS   = 132 # 132 --> CMD_GET_MEASUREMENTS
# CMD_GET_CURRENTS       = 133 # 133 --> CMD_GET_CURRENTS
# CMD_GET_MOTOR_COMMANDS = 149 # 149 --> CMD_GET_MOTOR_COMMANDS
# CMD_SET_BAUDRATE       = 144 # 144 --> CMD_SET_BAUDRATE
# CMD_ACTIVATE_ACK       = 147 # 147 --> CMD_ACTIVATE_ACK
# CMD_SET_INPUTS_ACK     = 148 # 148 --> CMD_SET_INPUTS_ACK, NEED PARAMS

# Device ID
ID = 1 # ID = 0 for broadcast

# Inputs references
ref_1 = 1000
ref_2 = 1000

close_all_serial_ports()

# Ottieni tutte le porte disponibili
com_ports = list_com_ports()
# Apri la prima porta COM disponibile
# serial_connection = open_serial_connection(com_ports[0])
serial_connection = open_serial_connection(choose_com_port())

if com_ports:
    # for ID in range(256):  # Itera sugli ID da 0 a 255
        # Apri la prima porta disponibile
        # serial_connection = open_serial_connection(com_ports[0])
        
        if serial_connection:
            qb_cmd_ping(ID, serial_connection)
            # qb_cmd_get_inputs(ID, serial_connection)
            time.sleep(1)
            # qb_cmd_ping_reverse(ID, serial_connection)
            #qb_cmd_boot(ID, serial_connection)
            # qb_cmd_get_measurements(ID, serial_connection)
            # qb_cmd_init_mem_reverse(ID, serial_connection)
            # qb_cmd_get_currents(ID, serial_connection)

        # Chiude la connessione seriale
        close_serial_connection(serial_connection)    







