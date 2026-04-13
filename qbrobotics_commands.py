#######################################################################################
####################    Python libraries for qbrobotics devices    ####################
#######################################################################################

import time
from qbrobotics_serial_utils import *


# COMMANDS

CMD_PING               = 0   # 0   --> CMD_PING
CMD_GET_INFO           = 6   # 6   --> CMD_GET_INFO, NEED PARAMS
CMD_BOOTLOADER         = 9   # 9   --> CMD_BOOTLOADER
CMD_ACTIVATE           = 128 # 128 --> CMD_ACTIVATE, NEED PARAMS
CMD_GET_ACTIVATE       = 129 # 129 --> CMD_GET_ACTIVATE
CMD_SET_INPUTS         = 130 # 130 --> CMD_SET_INPUTS, NEED PARAMS
CMD_GET_INPUTS         = 131 # 131 --> CMD_GET_INPUTS
CMD_GET_MEASUREMENTS   = 132 # 132 --> CMD_GET_MEASUREMENTS
CMD_GET_CURRENTS       = 133 # 133 --> CMD_GET_CURRENTS
CMD_GET_MOTOR_COMMANDS = 149 # 149 --> CMD_GET_MOTOR_COMMANDS
CMD_ACTIVATE_ACK       = 147 # 147 --> CMD_ACTIVATE_ACK
CMD_SET_INPUTS_ACK     = 148 # 148 --> CMD_SET_INPUTS_ACK, NEED PARAMS

######################################################################################
# WITHOUT PAYLOAD THE CHECKSUM IS EQUAL TO COMMAND
# PACKAGE LENGTH INCLUDES COMMAND, PAYLOAD AND CHECKSUM
######################################################################################


### CMD_PING ###
# cmd = 0 # 0 --> CMD_PING
# NO PAYLOAD 

# [ : : , ID , 1 , 2 , 0 , 0 ]

def qb_cmd_ping(ID, serial_connection):
    """
    Comando per inviare un ping al dispositivo.
    """
    # cmd 
    # pkt = [cmd] # insert command
    
    # send_with_ID(pkt,ID)
    print("\nCOMMAND: CMD_PING")
    # receive_ping()

    cmd = CMD_PING # 0 --> CMD_PING
    pkt = [cmd] # insert command
    if send_packet(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ping ricevuta:", packet)

def qb_cmd_ping_reverse(ID, serial_connection):
    """
    Comando per inviare un ping al dispositivo al contrario.
    """
    # cmd 
    # pkt = [cmd] # insert command
    
    # send_with_ID(pkt,ID)
    print("\nCOMMAND: CMD_PING_REVERSE")
    # receive_ping()

    cmd = CMD_PING # 0 --> CMD_PING
    pkt = [cmd] # insert command
    if send_packet_reverse(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ping ricevuta:", packet)            

######################################################################################

### CMD_GET_INFO ###
# cmd = 6 # 6 --> CMD_GET_INFO, NEED PARAMS
# PAYLOAD: 0 , 0

# [ : : , ID , 4 , 6 , 0 , 0 , 6 ]

def qb_cmd_get_info(ID, serial_connection):

    cmd = CMD_GET_INFO # 6 --> CMD_GET_INFO, NEED PARAMS
    pkt = [cmd] # insert command
    params = [0x00, 0x00] # payload
    for i in params:
        pkt.append(i)
    
    # send_brd(pkt)
    # send_with_ID(pkt,ID)
    if send_packet(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ricevuta:", packet)
    print("\nCOMMAND: CMD_GET_INFO\n")
    # receive_info()

### CMD_BOOTLOADER ###
# cmd = 9 # 9 --> CMD_BOOTLOADER
# NO PAYLOAD 

# [ : : , ID , 1 , 9 , 0 , 0 ]

def qb_cmd_boot(ID, serial_connection):
    # cmd 
    # pkt = [cmd] # insert command
    
    # send_with_ID(pkt,ID)
    print("\nCOMMAND: CMD_BOOTLOADER")
    # receive_ping()

    cmd = CMD_BOOTLOADER # 9
    pkt = [cmd] # insert command
    if send_packet(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ping ricevuta:", packet)


######################################################################################

### CMD_ACTIVATE ###
# cmd = 128 # 128 --> CMD_ACTIVATE, NEED PARAMS
# PARAMS: 1

# [ : : , ID , 3 , 128 , 1 , 129 ]

def qb_cmd_activate(ID, serial_connection):

    cmd = 128 # 128 --> CMD_ACTIVATE, NEED PARAMS
    pkt = [cmd] # insert command
    params = [0x03] # payload
    for i in params:
        pkt.append(i)
    
    if send_packet(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ricevuta:", packet)
    print("\nCOMMAND: CMD_ACTIVATE\n")

######################################################################################

### CMD_ACTIVATE_ACK ###

# cmd = 147 # 147 --> CMD_ACTIVATE_ACK, NEED PARAMS
# PARAMS: 1

# [ : : , ID , 3 , 147 , 1 , 146 ]

def qb_cmd_activate_ack(ID, serial_connection):

    cmd = 147 # 147 --> CMD_ACTIVATE_ACK, NEED PARAMS
    pkt = [cmd] # insert command
    params = [0x01] # payload
    for i in params:
        pkt.append(i)
    
    if send_packet(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ricevuta:", packet)
    print("\nCOMMAND: CMD_ACTIVATE_ACK\n")

######################################################################################

### CMD_GET_ACTIVATE ###

# cmd = 129 # 129 --> CMD_GET_ACTIVATE
# NO PAYLOAD 

# [ : : , ID , 1 , 2 , 129 , 129 ]

def qb_cmd_get_activate(ID, serial_connection):

    cmd = 129 # 129 --> CMD_GET_ACTIVATE
    pkt = [cmd] # insert command
    
    # send_brd(pkt)
    if send_packet(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ricevuta:", packet)
    print("\nCOMMAND: CMD_GET_ACTIVATE")

######################################################################################

### CMD_SET_INPUTS ###

# cmd = 130 # 130 --> CMD_SET_INPUTS, NEED PARAMS
# NO PAYLOAD 

# [ : : , ID , 1 , 2 , 130 , 130 ]

def qb_cmd_set_inputs(ID, input_1, input_2, serial_connection):

    print("Set Inputs to (" + str(input_1) + "," + str(input_2) + ")")
    cmd = 130 # 130 --> CMD_SET_INPUTS, NEED PARAMS
    pkt = [cmd] # insert command
    params = []

    # the inputs must be divided by 256 with module and oddment and convert to hex to send in the packet 

    in1_m = int(input_1 / 256)
    in1_r = input_1 % 256
    in2_m = int(input_2 / 256)
    in2_r = input_2 % 256

    in1_m_h = hex(in1_m)
    params.append(in1_m_h)
    in1_r_h = hex(in1_r)
    params.append(in1_r_h)

    print(params)

    # vet = []


    print((in1_m), (in1_r), (in2_m), (in2_r))
    print(hex(in1_m), hex(in1_r), hex(in2_m), hex(in2_r))

    params = [hex(in2_m), hex(in2_r)] # payload

    # for i in range(4):
    #     par = str(params[i]).split("'")[1].split("'")[0]
    #     vet[i] = par

    print(params)
    

    for i in params:
        pkt.append(i)

    print(pkt)
    # send_brd(pkt)
    if send_packet(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ricevuta:", packet)
    print("\nCOMMAND: CMD_SET_INPUTS\n")

######################################################################################

### CMD_GET_INPUTS ###
def qb_cmd_get_inputs(ID, serial_connection):

    # cmd = 131 # 131 --> CMD_GET_INPUTS
    # pkt = [cmd] # insert command
    
    # # send_brd(pkt)
    # send_with_ID(pkt,ID)
    # print("\nCOMMAND: CMD_GET_INPUTS")
    # receive()

    cmd = CMD_GET_INPUTS # 131 --> CMD_GET_INPUTS
    pkt = [cmd] # insert command
    if send_packet(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ping ricevuta:", packet)

######################################################################################

### CMD_GET_MEASUREMENTS ###
def qb_cmd_get_measurements(ID, serial_connection):

    # cmd = 132 # 132 --> CMD_GET_MEASUREMENTS
    # pkt = [cmd] # insert command
    
    # # send_brd(pkt)
    # send_with_ID(pkt,ID)
    print("\nCOMMAND: CMD_GET_MEASUREMENTS")
    # # receive()
    # receive_get_meas()
    
    cmd = CMD_GET_MEASUREMENTS # 132 --> CMD_GET_MEASUREMENTS
    pkt = [cmd] # insert command
    if send_packet(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ping ricevuta:", packet)

######################################################################################

### CMD_GET_CURRENTS ###
def qb_cmd_get_currents(ID, serial_connection):

    # cmd = 133 # 133 --> CMD_GET_CURRENTS
    # pkt = [cmd] # insert command
    
    # # send_brd(pkt)
    # send_with_ID(pkt,ID)
    print("\nCOMMAND: CMD_GET_CURRENTS")
    # receive()
    # receive_get_curr()

    cmd = CMD_GET_CURRENTS # 133 --> CMD_GET_CURRENTS
    pkt = [cmd] # insert command
    if send_packet(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ping ricevuta:", packet)

######################################################################################


### CMD_SET_BAUDRATE ###
# cmd = 144 # 144 --> CMD_SET_BAUDRATE, NEED PARAMS
# PARAMS: CLOCK_DIVIDER

# [ : : , ID , 3 , 144 , PARAM , CRC ]

def qb_cmd_set_baudrate(ID, serial_connection, clk_div):

    cmd = 144 # 144 --> CMD_SET_BAUDRATE, NEED PARAMS
    pkt = [cmd] # insert command
    params = clk_div # payload
    for i in params:
        pkt.append(i)
    
    send_packet(ID, serial_connection, pkt)
    # send_brd(pkt)
    # send_with_ID(pkt,ID)
    print("\nCOMMAND: CMD_SET_BAUDRATE\n")

######################################################################################


### CMD_GET_MOTOR_COMMANDS ###
def qb_cmd_get_motor_commands(ID, serial_connection):

    cmd = 149 # 149 --> CMD_GET_MOTOR_COMMANDS
    pkt = [cmd]

    # send_brd(pkt)
    if send_packet(ID, serial_connection, pkt):
        packet = receive_packet(serial_connection, cmd)
        if packet:
            print("Risposta ricevuta:", packet)
    print("\nCOMMAND: CMD_GET_MOTOR_COMMANDS")
    # receive()

######################################################################################


### CMD_PING ###
# cmd = 0 # 0 --> CMD_PING
# NO PAYLOAD 

# [ : : , ID , 1 , 2 , 0 , 0 ]

def qb_cmd_test(ID, serial_connection):
    """
    Comando per inviare un ping al dispositivo.
    """
    # cmd 
    # pkt = [cmd] # insert command
    
    # send_with_ID(pkt,ID)
    # print("\nCOMMAND: CMD_PING")
    # receive_ping()

    cmd = CMD_PING # 0 --> CMD_PING
    pkt = [cmd] # insert command
    send_packet(ID, serial_connection, pkt)
    

######################################################################################
######################################################################################