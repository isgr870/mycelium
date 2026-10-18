import socket
import logging

logger = logging.getLogger(__name__)

class MeshTransport:
    def __init__(self, host='0.0.0.0', port=9000):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
    def bind(self):
        try:
            self.sock.bind((self.host, self.port))
            logger.info("MeshTransport bound successfully to %s:%s", self.host, self.port)
        except OSError as e:
            logger.error("Failed to bind socket transport: %s", e)
            raise
