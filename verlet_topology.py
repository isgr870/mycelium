import math

class VerletParticle:
    def __init__(self, peer_id, x, y, mass=1.0):
        self.id = peer_id
        self.x = x
        self.y = y
        self.old_x = x
        self.old_y = y
        self.mass = mass
        self.pinned = False

    def update(self, dt=0.016, damping=0.98, gravity_y=0.0):
        if self.pinned:
            return
        vx = (self.x - self.old_x) * damping
        vy = (self.y - self.old_y) * damping + (gravity_y * dt * dt)
        
        self.old_x = self.x
        self.old_y = self.y
        self.x += vx
        self.y += vy

class VerletSpring:
    def __init__(self, p1, p2, rest_length, stiffness=0.1):
        self.p1 = p1
        self.p2 = p2
        self.rest_length = rest_length  # Driven by network latency (ms * scale)
        self.stiffness = stiffness      # Driven by link stability

    def satisfy(self):
        dx = self.p2.x - self.p1.x
        dy = self.p2.y - self.p1.y
        dist = math.hypot(dx, dy)
        if dist == 0:
            return
        
        diff = (dist - self.rest_length) / dist
        transl_x = dx * diff * self.stiffness
        transl_y = dy * diff * self.stiffness

        if not self.p1.pinned:
            self.p1.x += transl_x * 0.5
            self.p1.y += transl_y * 0.5
        if not self.p2.pinned:
            self.p2.x -= transl_x * 0.5
            self.p2.y -= transl_y * 0.5

class VerletMeshSimulation:
    def __init__(self):
        self.particles = {}
        self.springs = []

    def add_peer(self, peer_id, x, y, pinned=False):
        p = VerletParticle(peer_id, x, y)
        p.pinned = pinned
        self.particles[peer_id] = p
        return p

    def connect_peers(self, id1, id2, latency_ms, packet_loss=0.0):
        if id1 in self.particles and id2 in self.particles:
            rest_len = max(30.0, latency_ms * 2.0)
            stiffness = max(0.01, 0.2 - (packet_loss * 0.2))
            
            spring = VerletSpring(self.particles[id1], self.particles[id2], rest_len, stiffness)
            self.springs.append(spring)

    def step(self, iterations=3):
        for p in self.particles.values():
            p.update()
        for _ in range(iterations):
            for s in self.springs:
                s.satisfy()

    def get_state(self):
        return {
            'nodes': [{ 'id': p.id, 'x': round(p.x, 2), 'y': round(p.y, 2) } for p in self.particles.values()],
            'links': [{ 'p1': s.p1.id, 'p2': s.p2.id, 'len': round(math.hypot(s.p2.x - s.p1.x, s.p2.y - s.p1.y), 2) } for s in self.springs]
        }
