"""
Скрипт генерирует PCAP-файл с шумовым HTTP-трафиком и одним интересным POST /login,
в теле которого передаётся флаг.
"""
import os
import base64
from scapy.all import Ether, IP, TCP, Raw, PcapWriter

FLAG = os.environ.get("FLAG", "flag{w1r3sh4rk_rul3s_th3_n3t}")
PCAP_PATH = "/app/static/capture.pcap"

CLIENT_MAC = "02:00:00:00:00:01"
SERVER_MAC = "02:00:00:00:00:02"
CLIENT_IP = "10.13.37.10"
SERVER_IP = "10.13.37.50"
SPORT = 54321
DPORT = 8080


def pkt(payload: bytes, src_ip: str, dst_ip: str, sport: int, dport: int,
        seq: int, ack: int, flags: str) -> Ether:
    """Собирает полный Ethernet/IP/TCP/Raw пакет."""
    return (
        Ether(src=CLIENT_MAC, dst=SERVER_MAC) /
        IP(src=src_ip, dst=dst_ip) /
        TCP(sport=sport, dport=dport, seq=seq, ack=ack, flags=flags) /
        Raw(load=payload)
    )


def build_pcap():
    os.makedirs(os.path.dirname(PCAP_PATH), exist_ok=True)

    writer = PcapWriter(PCAP_PATH, linktype=1)

    cseq = 100
    sseq = 500

    # TCP handshake
    writer.write(pkt(b"", CLIENT_IP, SERVER_IP, SPORT, DPORT, cseq, 0, "S"))
    cseq += 1
    writer.write(pkt(b"", SERVER_IP, CLIENT_IP, DPORT, SPORT, sseq, cseq, "SA"))
    sseq += 1
    writer.write(pkt(b"", CLIENT_IP, SERVER_IP, SPORT, DPORT, cseq, sseq, "A"))

    # --- HTTP GET /index.html (noise) ---
    get_req = b"GET /index.html HTTP/1.1\r\nHost: portal.corp.local\r\nUser-Agent: Mozilla/5.0\r\n\r\n"
    writer.write(pkt(get_req, CLIENT_IP, SERVER_IP, SPORT, DPORT, cseq, sseq, "PA"))
    cseq += len(get_req)
    get_resp = b"HTTP/1.1 200 OK\r\nContent-Length: 23\r\n\r\nWelcome to the portal."
    writer.write(pkt(get_resp, SERVER_IP, CLIENT_IP, DPORT, SPORT, sseq, cseq, "PA"))
    sseq += len(get_resp)
    writer.write(pkt(b"", CLIENT_IP, SERVER_IP, SPORT, DPORT, cseq, sseq, "A"))

    # --- HTTP GET /api/status (noise, JSON) ---
    get2 = b"GET /api/status HTTP/1.1\r\nHost: portal.corp.local\r\nAccept: application/json\r\n\r\n"
    writer.write(pkt(get2, CLIENT_IP, SERVER_IP, SPORT, DPORT, cseq, sseq, "PA"))
    cseq += len(get2)
    get2_resp = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 27\r\n\r\n{\"status\":\"ok\",\"users\":42}"
    writer.write(pkt(get2_resp, SERVER_IP, CLIENT_IP, DPORT, SPORT, sseq, cseq, "PA"))
    sseq += len(get2_resp)
    writer.write(pkt(b"", CLIENT_IP, SERVER_IP, SPORT, DPORT, cseq, sseq, "A"))

    # --- HTTP POST /login (flag) ---
    body = f"username=admin\u0026password={FLAG}".encode()
    post_req = (
        b"POST /login HTTP/1.1\r\n"
        b"Host: portal.corp.local\r\n"
        b"Content-Type: application/x-www-form-urlencoded\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"User-Agent: CorpLogin/1.0\r\n"
        b"\r\n"
    ) + body
    writer.write(pkt(post_req, CLIENT_IP, SERVER_IP, SPORT, DPORT, cseq, sseq, "PA"))
    cseq += len(post_req)
    post_resp = b"HTTP/1.1 302 Found\r\nLocation: /dashboard\r\nSet-Cookie: session=DEADBEEF; Path=/\r\nContent-Length: 0\r\n\r\n"
    writer.write(pkt(post_resp, SERVER_IP, CLIENT_IP, DPORT, SPORT, sseq, cseq, "PA"))
    sseq += len(post_resp)
    writer.write(pkt(b"", CLIENT_IP, SERVER_IP, SPORT, DPORT, cseq, sseq, "A"))

    # --- DNS-over-HTTPS noise: base64-encoded flag in User-Agent (alternative path) ---
    hint_b64 = base64.b64encode(FLAG.encode()).decode()
    get3 = (
        f"GET /dns-query?type=A\u0026name=secret.corp.local HTTP/1.1\r\n"
        f"Host: dns.corp.local\r\n"
        f"User-Agent: DoH-Client/2.0 {hint_b64}\r\n\r\n"
    ).encode()
    writer.write(pkt(get3, CLIENT_IP, SERVER_IP, SPORT, DPORT, cseq, sseq, "PA"))
    cseq += len(get3)
    get3_resp = b"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\nContent-Length: 4\r\n\r\n\x00\x00\x00\x00"
    writer.write(pkt(get3_resp, SERVER_IP, CLIENT_IP, DPORT, SPORT, sseq, cseq, "PA"))
    sseq += len(get3_resp)
    writer.write(pkt(b"", CLIENT_IP, SERVER_IP, SPORT, DPORT, cseq, sseq, "A"))

    # FIN handshake
    writer.write(pkt(b"", CLIENT_IP, SERVER_IP, SPORT, DPORT, cseq, sseq, "FA"))
    cseq += 1
    writer.write(pkt(b"", SERVER_IP, CLIENT_IP, DPORT, SPORT, sseq, cseq, "FA"))

    writer.close()
    print(f"[+] PCAP written to {PCAP_PATH}")


if __name__ == "__main__":
    build_pcap()
