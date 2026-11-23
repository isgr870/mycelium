from spore_sync import SimpleBloomFilter

node_a_filter = SimpleBloomFilter(size=64, hash_count=2)
node_b_filter = SimpleBloomFilter(size=64, hash_count=2)

node_a_filter.add("spore_chunk_99")
node_a_filter.add("spore_chunk_102")

node_b_filter.add("spore_chunk_102")

diff = node_a_filter.get_diff(node_b_filter.bit_array)
print("Missing spored payloads identified for sync via Bloom diff:", len(diff) > 0)
print("Sync diff bit count:", len(diff))
