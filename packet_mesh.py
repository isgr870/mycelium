import struct
import zlib
import json

# Header Specification:
# [4 Bytes: Magic Magic "MYCL"] [1 Byte: Packet Type] [4 Bytes: Payload Length] [4 Bytes: CRC32 Checksum]
MAGIC = b"MYCL"
HEADER_FORMAT = "!4sBII"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Packet Types
TYPE_HANDSHAKE = 0x01
TYPE_GOSSIP    = 0x02
TYPE_MSG       = 0x03
TYPE_PING      = 0x04

def pack_packet(packet_type: int, payload_data: dict) -> bytes:
    """Serializes a JSON-compatible dictionary into a binary frame with CRC32 verification."""
    raw_payload = json.dumps(payload_data).encode('utf-8')
    payload_len = len(raw_payload)
    crc32 = zlib.crc32(raw_payload) & 0xffffffff
    
    header = struct.pack(HEADER_FORMAT, MAGIC, packet_type, payload_len, crc32)
    return header + raw_payload

def unpack_header(header_bytes: bytes):
    """Unpacks and validates binary packet header."""
    if len(header_bytes) < HEADER_SIZE:
        return None
    magic, packet_type, payload_len, crc32 = struct.unpack(HEADER_FORMAT, header_bytes)
    if magic != MAGIC:
        raise ValueError("Invalid magic bytes: Not a Mycelium packet frame")
    return packet_type, payload_len, crc32

def verify_and_unpack_payload(payload_bytes: bytes, expected_crc32: int) -> dict:
    """Verifies CRC32 checksum and decodes JSON payload."""
    computed_crc = zlib.crc32(payload_bytes) & 0xffffffff
    if computed_crc != expected_crc32:
        raise ValueError("Corrupted packet frame: CRC32 checksum mismatch")
    return json.loads(payload_bytes.decode('utf-8'))

if __name__ == "__main__":
    # Self-test packet construction and parsing
    test_payload = {"source": "Node1", "msg": "Merged Mesh Frame Test"}
    frame = pack_packet(TYPE_MSG, test_payload)
    p_type, p_len, p_crc = unpack_header(frame[:HEADER_SIZE])
    decoded = verify_and_unpack_payload(frame[HEADER_SIZE:HEADER_SIZE+p_len], p_crc)
    
    print(f"[+] Packet Test Success!")
    print(f"    Frame Size: {len(frame)} bytes | Payload Type: {p_type} | CRC32: {hex(p_crc)}")
    print(f"    Decoded Payload: {decoded}")
