"""Small bounded queue with priorities, aging and replacement before dispatch."""
import asyncio
from collections import Counter
from dataclasses import dataclass
import itertools
import time


@dataclass(slots=True)
class Job:
    user: str
    text: str
    nickname: str
    kind: str
    priority: int
    received: float
    expires: float
    command: str = ''
    request_id: str = ''
    id: str = ''
    sequence: int = 0
    payload: dict | None = None


class WorkQueue:
    def __init__(self, capacity, *, clock=time.monotonic, on_drop=None):
        self.capacity, self.clock = capacity, clock
        self.items = []
        self.stats = Counter()
        self.signal = asyncio.Event()
        self.sequence = itertools.count()
        self.on_drop = on_drop or (lambda job:None)

    def purge(self):
        expired = [job for job in self.items if job.expires <= self.clock()]
        for job in expired:
            self.items.remove(job)
            self.on_drop(job)
        self.stats['expired'] += len(expired)
        return expired

    def offer(self, job, *, coalesce=True):
        self.purge()
        if job.expires <= self.clock():
            self.stats['expired'] += 1
            return False
        if coalesce:
            old = next((item for item in self.items if item.user == job.user),None)
            if old:
                if old.priority < job.priority: return False
                self.items.remove(old)
                self.on_drop(old)
                self.stats['coalesced'] += 1
        if len(self.items) >= self.capacity:
            # Critical/high events can displace only jobs which have not started.
            victim = max(self.items,key=lambda item:(item.priority,-item.received))
            if victim.priority < job.priority:
                self.stats['saturated'] += 1
                return False
            self.items.remove(victim)
            self.on_drop(victim)
            self.stats['displaced'] += 1
        job.sequence = next(self.sequence)
        self.items.append(job)
        self.signal.set()
        self.stats['accepted'] += 1
        return True

    async def get(self, *, eligible=lambda job:True):
        while True:
            self.purge()
            possible = [item for item in self.items if eligible(item)]
            if possible:
                now=self.clock()
                # A low-priority job gains one rank per three seconds of waiting.
                job=min(possible,key=lambda item:(item.priority-(now-item.received)/3,item.sequence))
                self.items.remove(job)
                return job
            self.signal.clear()
            await self.signal.wait()

    def remove(self, predicate):
        removed = [job for job in self.items if predicate(job)]
        for job in removed: self.items.remove(job)
        return removed

    def clear(self):
        removed = self.items[:]
        self.items.clear()
        return removed

    def snapshot(self):
        self.purge()
        return {'pending':len(self.items),'oldest_age_s':round(max((self.clock()-j.received for j in self.items),default=0),2),
                'stats':dict(self.stats)}
