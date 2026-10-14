import hmac
import hashlib
import json
import time

class SwarmRAGNode:
    def __init__(self, node_id, secret_key):
        self.node_id = node_id
        self.secret_key = secret_key.encode('utf-8')
        self.local_vector_store = []

    def add_knowledge(self, chunk_id, text, embedding):
        self.local_vector_store.append({
            'id': chunk_id,
            'text': text,
            'embedding': embedding
        })

    def sign_query(self, query_payload):
        payload_str = json.dumps(query_payload, sort_keys=True)
        signature = hmac.new(self.secret_key, payload_str.encode('utf-8'), hashlib.sha256).hexdigest()
        return {
            'node_id': self.node_id,
            'payload': query_payload,
            'signature': signature,
            'timestamp': time.time()
        }

    def verify_and_search(self, signed_packet, query_vector, threshold=0.7):
        payload_str = json.dumps(signed_packet['payload'], sort_keys=True)
        expected_sig = hmac.new(self.secret_key, payload_str.encode('utf-8'), hashlib.sha256).hexdigest()
        
        if not hmac.compare_digest(expected_sig, signed_packet['signature']):
            return {'error': 'Invalid cryptographic signature', 'matches': []}

        matches = []
        for item in self.local_vector_store:
            similarity = self._cosine_similarity(query_vector, item['embedding'])
            if similarity >= threshold:
                matches.append({
                    'chunk_id': item['id'],
                    'text': item['text'],
                    'score': round(similarity, 4),
                    'source_node': self.node_id
                })
        return {'error': None, 'matches': matches}

    def _cosine_similarity(self, v1, v2):
        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm1 = (sum(a * a for a in v1)) ** 0.5
        norm2 = (sum(b * b for b in v2)) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)
