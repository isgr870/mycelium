class Boundary:
    def __init__(self, x, y, w, h):
        self.x = x  # Center x
        self.y = y  # Center y
        self.w = w  # Half-width
        self.h = h  # Half-height

    def contains(self, px, py):
        return (px >= self.x - self.w and px < self.x + self.w and
                py >= self.y - self.h and py < self.y + self.h)

    def intersects(self, range_bound):
        return not (range_bound.x - range_bound.w > self.x + self.w or
                    range_bound.x + range_bound.w < self.x - self.w or
                    range_bound.y - range_bound.h > self.y + self.h or
                    range_bound.y + range_bound.h < self.y - self.h)

class QuadtreeNode:
    def __init__(self, boundary, capacity=4):
        self.boundary = boundary
        self.capacity = capacity
        self.points = []  # List of dicts: {'id': peer_id, 'x': x, 'y': y}
        self.divided = False

    def subdivide(self):
        x, y, w, h = self.boundary.x, self.boundary.y, self.boundary.w / 2, self.boundary.h / 2
        self.nw = QuadtreeNode(Boundary(x - w, y - h, w, h), self.capacity)
        self.ne = QuadtreeNode(Boundary(x + w, y - h, w, h), self.capacity)
        self.sw = QuadtreeNode(Boundary(x - w, y + h, w, h), self.capacity)
        self.se = QuadtreeNode(Boundary(x + w, y + h, w, h), self.capacity)
        self.divided = True

    def insert(self, point):
        if not self.boundary.contains(point['x'], point['y']):
            return False

        if len(self.points) < self.capacity:
            self.points.append(point)
            return True

        if not self.divided:
            self.subdivide()

        return (self.nw.insert(point) or self.ne.insert(point) or
                self.sw.insert(point) or self.se.insert(point))

    def query(self, range_bound, found=None):
        if found is None:
            found = []

        if not self.boundary.intersects(range_bound):
            return found

        for p in self.points:
            if range_bound.contains(p['x'], p['y']):
                found.append(p)

        if self.divided:
            self.nw.query(range_bound, found)
            self.ne.query(range_bound, found)
            self.sw.query(range_bound, found)
            self.se.query(range_bound, found)

        return found
