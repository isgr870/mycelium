from swarm_rag import SwarmRAGNode

node_alpha = SwarmRAGNode('node_alpha', secret_key='mycelium-mesh-shared-secret')
node_beta = SwarmRAGNode('node_beta', secret_key='mycelium-mesh-shared-secret')

node_beta.add_knowledge(
    chunk_id='chunk_01', 
    text='Verlet integration is ideal for real-time physics sandboxes on mobile browsers.', 
    embedding=[0.85, 0.12, 0.03]
)

query_data = {'query_vector': [0.80, 0.15, 0.05], 'max_results': 1}
signed_packet = node_alpha.sign_query(query_data)
response = node_beta.verify_and_search(signed_packet, query_vector=[0.80, 0.15, 0.05], threshold=0.7)
print("Swarm RAG Verification & Search Results:", response)
