from quadtree import Boundary, QuadtreeNode

domain = Boundary(500, 500, 500, 500)
qtree = QuadtreeNode(domain, capacity=2)

qtree.insert({'id': 'peer_alpha', 'x': 120, 'y': 150})
qtree.insert({'id': 'peer_beta', 'x': 850, 'y': 900})
qtree.insert({'id': 'peer_gamma', 'x': 140, 'y': 160})

search_area = Boundary(150, 150, 100, 100)
neighbors = qtree.query(search_area)
print("Localized Peers Found:", [p['id'] for p in neighbors])
