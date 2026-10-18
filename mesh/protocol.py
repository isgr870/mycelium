import hmac
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

class MeshProtocol:
    @staticmethod
    def encode_packet(payload: dict, secret_key: str) -> bytes:
        payload_str = json.dumps(payload, sort_keys=True)
        signature = hmac.new(secret_key.encode('utf-8'), payload_str.encode('utf-8'), hashlib.sha256).hexdigest()
        packet = {'payload': payload, 'signature': signature}
        return json.dumps(packet).encode('utf-8')

    @staticmethod
    def decode_packet(data: bytes, secret_key: str) -> dict:
        try:
            packet = json.loads(data.decode('utf-8'))
            payload_str = json.dumps(packet['payload'], sort_keys=True)
            expected = hmac.new(secret_key.encode('utf-8'), payload_str.encode('utf-8'), hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, packet['signature']):
                return packet['payload']
        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Packet decoding failed safely: %s", e)
        return {}
