"""C3 panel diagnostikasi: UDP discovery javobini xom holda chiqaradi va TCP/UDP 4370 ni sinaydi."""
import socket
import sys
from c3 import C3, consts

PANEL = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.201"

print("=== 1. UDP discovery (broadcast 65535) ===")
msg = C3._construct_message(None, None, consts.Command.DISCOVER, consts.C3_DISCOVERY_MESSAGE)
local_ips = {ip[-1][0] for ip in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
for ip in local_ips:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(2)
    try:
        s.bind((ip, 0))
        s.sendto(msg, ("255.255.255.255", consts.C3_PORT_BROADCAST))
        while True:
            data, addr = s.recvfrom(65535)
            print(f"[{ip}] javob {addr}: {len(data)} bayt")
            print("  HEX :", data.hex(" "))
            print("  TEXT:", data[8:-3].decode("latin-1", "replace"))
    except socket.timeout:
        pass
    except OSError as e:
        print(f"[{ip}] xato: {e}")
    finally:
        s.close()

print(f"\n=== 2. TCP {PANEL}:4370 ===")
try:
    socket.create_connection((PANEL, 4370), timeout=3).close()
    print("OCHIQ")
except OSError as e:
    print("YOPIQ:", e)

print(f"\n=== 3. UDP {PANEL}:4370 (CONNECT_SESSION) ===")
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(3)
try:
    s.sendto(C3._construct_message(0xFEFE, -258, consts.Command.CONNECT_SESSION, None), (PANEL, 4370))
    data, addr = s.recvfrom(65535)
    print(f"JAVOB BOR: {data.hex(' ')}")
except Exception as e:
    print("javob yo'q:", e)
