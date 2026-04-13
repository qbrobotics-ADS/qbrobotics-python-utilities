# serial_utils.py

import serial
import serial.tools.list_ports
import time

######################################################################################
########################## Funzioni Gestione Connessione Seriali #####################
######################################################################################

# COMMANDS

CMD_PING               = 0   # 0   --> CMD_PING
CMD_GET_INFO           = 6   # 6   --> CMD_GET_INFO, NEED PARAMS
CMD_ACTIVATE           = 128 # 128 --> CMD_ACTIVATE, NEED PARAMS
CMD_GET_ACTIVATE       = 129 # 129 --> CMD_GET_ACTIVATE
CMD_SET_INPUTS         = 130 # 130 --> CMD_SET_INPUTS, NEED PARAMS
CMD_GET_INPUTS         = 131 # 131 --> CMD_GET_INPUTS
CMD_GET_MEASUREMENTS   = 132 # 132 --> CMD_GET_MEASUREMENTS
CMD_GET_CURRENTS       = 133 # 133 --> CMD_GET_CURRENTS
CMD_GET_MOTOR_COMMANDS = 149 # 149 --> CMD_GET_MOTOR_COMMANDS
CMD_ACTIVATE_ACK       = 147 # 147 --> CMD_ACTIVATE_ACK
CMD_SET_INPUTS_ACK     = 148 # 148 --> CMD_SET_INPUTS_ACK, NEED PARAMS

def close_all_serial_ports():
    """
    Chiude tutte le porte seriali aperte per evitare conflitti.
    """
    ports = serial.tools.list_ports.comports()

    for port in ports:
        try:
            ser = serial.Serial(port.device)
            if ser.is_open:
                ser.close()
                print(f"Porta seriale chiusa: {port.device}")
        except (serial.SerialException, OSError) as e:
            print(f"Errore nel chiudere la porta {port.device}: {e}")

def list_com_ports():
    """
    Restituisce una lista delle porte COM disponibili.
    """
    ports = serial.tools.list_ports.comports()
    com_ports = [port.device for port in ports]

    if com_ports:
        print("Porte COM disponibili:")
        for port in com_ports:
            print(f"- {port}")
        return com_ports
    else:
        print("Nessuna porta COM trovata.")
        return []

def choose_com_port():
    """
    Mostra le porte COM disponibili e permette all'utente di sceglierne una.
    Restituisce la stringa della porta selezionata (es. 'COM3') oppure None.
    """
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("Nessuna porta COM trovata.")
        return None

    print("\nPorte COM disponibili:")
    for idx, port in enumerate(ports):
        # Se vuoi più info: descrizione, ecc.:
        # print(f"[{idx}] {port.device} - {port.description}")
        print(f"[{idx}] {port.device}")

    while True:
        choice = input("Seleziona l'indice della porta COM (o premi Invio per annullare): ").strip()

        if choice == "":
            print("Selezione annullata.")
            return None

        if not choice.isdigit():
            print("Input non valido. Inserisci un numero intero.")
            continue

        idx = int(choice)
        if 0 <= idx < len(ports):
            selected_port = ports[idx].device
            print(f"Hai selezionato: {selected_port}")
            return selected_port
        else:
            print(f"Indice fuori range. Inserisci un numero tra 0 e {len(ports)-1}.")

def open_serial_connection(port, baudrate=2000000, bytesize=8, parity='N', timeout=None):
    """
    Apre una connessione seriale sulla porta specificata con i parametri forniti.
    """
    if port is None:
        print("Nessuna porta selezionata, impossibile aprire la connessione seriale.")
        return None

    try:
        serial_connection = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity,
            timeout=timeout
        )
        print(f"\nConnessione seriale aperta su {port} con baudrate {baudrate}.")
        time.sleep(1)
        return serial_connection
    except serial.SerialException as e:
        print(f"Errore nell'apertura della porta seriale {port}: {e}")
        return None

def close_serial_connection(serial_connection):
    """
    Chiude la connessione seriale fornita se è aperta.
    """
    if serial_connection and serial_connection.is_open:
        serial_connection.close()
        print(f"\nConnessione seriale chiusa su {serial_connection.port}.\n")
        return True
    return False

######################################################################################
########################### Funzioni per Invio e Ricezione Pacchetti #################
######################################################################################

def send_packet(device_id, serial_connection, pkt):
    """
    Invio di un pacchetto dati a un dispositivo qbrobotics.
    """
    if not serial_connection or not serial_connection.is_open:
        print("Connessione seriale non disponibile.")
        return False

    # Header: ':', ':', ID
    p_send = [58, 58, device_id]  # 58 refers to ':'
    
    # Payload length + LRC
    p_send.append(len(pkt) + 1)
    p_send.extend(pkt)
    p_send.append(LRC(pkt))

    print(f"\nSending the package to the device with ID {device_id} on {serial_connection.port} port")
    print("Package sent:", p_send)
    
    packet = bytearray(p_send)
    serial_connection.write(packet)
    serial_connection.flush()
    return True

def send_packet_reverse(device_id, serial_connection, pkt):
    """
    Invio di un pacchetto dati a un dispositivo qbrobotics con ordine invertito.
    """
    if not serial_connection or not serial_connection.is_open:
        print("Connessione seriale non disponibile.")
        return False

    # Costruzione pacchetto originale
    p_send = [58, 58, device_id]  # Header
    p_send.append(len(pkt) + 1)   # Lunghezza payload + LRC
    p_send.extend(pkt)            # Payload
    p_send.append(LRC(pkt))       # Checksum

    # Inversione dell'ordine del pacchetto
    p_send_reversed = p_send[::-1]  # Giriamo tutta la lista

    print(f"\nInvio pacchetto invertito al dispositivo ID {device_id} su {serial_connection.port}")
    print("Pacchetto originale:", p_send)
    print("Pacchetto invertito:", p_send_reversed)
    
    # Invio del pacchetto invertito
    packet = bytearray(p_send_reversed)
    serial_connection.write(packet)
    serial_connection.flush()
    
    return True

def receive_packet(serial_connection, command):
    """
    Riceve un pacchetto dati dalla connessione seriale.
    """
    if not serial_connection or not serial_connection.is_open:
        print("Serial connection not available.")
        return None

    print(f"Reading package on {serial_connection.port}")

    packet_length = serial_connection.in_waiting

    if(packet_length <= 0):
        print("NO PACKET RECEIVED\n")
        return False

    bytesToRead = serial_connection.readline(packet_length)

    bytesRead = str(bytesToRead).split("b'")[1].split("'")[0]
    print("\nPACKET RECEIVED (hex): ", bytesRead)

    pck_rec = [58, 58]  # 58 refers to :
    for pos, char in enumerate(bytesRead):
        if(char == "\\"):
            hex_value = ("0" + bytesRead[pos+1:pos+4])
            int_value = int(hex_value, 0)
            pck_rec.append(int_value)

    print("\nPACKET RECEIVED (int): ", pck_rec)
    print("")

    # PARSE THE PAYLOAD
    load = []
    cmd = pck_rec[4]  # in the packet the payload starts after the command
    for pos, char in enumerate(pck_rec):
        if(char == cmd):  # now pos is equal to the position of the command in the packet
            value = pck_rec[pos+1:]  # the payload starts at pos+1 position in the packet
            load.append(value)
    payl = load[0]

    if (command == CMD_PING):
        payload = payl[:len(payl)]
        pck_rec.append(LRC(payload))
        print("\nPACKET RECEIVED with LRC (int): ", pck_rec)
        print("")
        print("\nPAYLOAD RECEIVED (int): ", payload)
        serial_number = (((((payload[0]*256)+payload[1])*256+payload[2])*256)+payload[3])
        print("\nDEVICE SERIAL NUMBER:", serial_number)
        print("")

    if (command == CMD_GET_MEASUREMENTS):
        payload = payl[:len(payl)]
        pck_rec.append(LRC(payload))
        print("\nPACKET RECEIVED with LRC (int): ", pck_rec)
        print("")
        print("\nPAYLOAD RECEIVED (int): ", payload)

        # Calcola il numero di encoder (misure) disponibili
        num_encoders = len(payload) // 2

        # Loop per leggere i valori di payload e calcolare meas
        for i in range(num_encoders):
            start_index = i * 2
            meas = (payload[start_index] * 256) + payload[start_index + 1]
            print(f"\nEncoder {i + 1}: {meas}")

    if (command == CMD_GET_CURRENTS):
        payload = payl[:len(payl)-1]
        print("\nPAYLOAD RECEIVED (int): ", payload)
        meas1 = ((payload[0]*256)+payload[1])
        print("\nMotor Current 1: ", meas1)
        meas2 = ((payload[2]*256)+payload[3])
        print("\nMotor Current 2: ", meas2)
        print("")

######################################################################################
########################### Funzione di Utilità ######################################
######################################################################################

# Calculating Checksum LRC: Longitudinal Redundancy Check
def LRC(pkt):
    """
    Calcola il checksum LRC (Longitudinal Redundancy Check) di un pacchetto.
    """
    lrc = 0
    for i in pkt:
        lrc = (lrc ^ i)
    return lrc
