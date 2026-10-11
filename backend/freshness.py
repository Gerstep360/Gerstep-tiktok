"""Bounded duplicate memory and conservative intake synchronization."""
from collections import OrderedDict
import time


class Freshness:
    def __init__(self, clock=time.monotonic, wall=time.time):
        self.clock, self.wall = clock, wall
        self.ids, self.connected = OrderedDict(), False

    def connect(self):
        self.connected = True
        self.started, self.started_wall = self.clock(), self.wall()

    def disconnect(self): self.connected = False

    def accept(self, event):
        if not self.connected: return False
        now, wall = self.clock(), self.wall()
        while self.ids and now - next(iter(self.ids.values())) >= 600: self.ids.popitem(last=False)
        base = getattr(event, 'base_message', None)
        try: stamp = float(getattr(base, 'create_time', 0) or 0)
        except (TypeError, ValueError): stamp = 0
        if stamp > 1e12: stamp /= 1000
        if 1e9 < stamp <= wall + 5:
            if stamp < self.started_wall or wall - stamp > 10: return False
        elif now - self.started < 3: return False
        identifier = getattr(base, 'message_id', None)
        if identifier:
            key = (type(event).__name__, str(identifier))
            if key in self.ids: return False
            self.ids[key] = now
            while len(self.ids) > 4096: self.ids.popitem(last=False)
        return True
