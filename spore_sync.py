import hashlib

class SimpleBloomFilter:
    def __init__(self, size=128, hash_count=3):
        self.size = size
        self.hash_count = hash_count
        self.bit_array = [0] * size

    def _hashes(self, item):
        for i in range(self.hash_count):
            h = int(hashlib.sha256(f"{item}:{i}".encode('utf-8')).hexdigest(), 16)
            yield h % self.size

    def add(self, item):
        for h in self._hashes(item):
            self.bit_array[h] = 1

    def __contains__(self, item):
        return all(self.bit_array[h] for h in self._hashes(item))

    def get_diff(self, other_bits):
        return [i for i, (a, b) in enumerate(zip(self.bit_array, other_bits)) if a == 1 and b == 0]
