"""Shared sliding-window budgets include retries, cancelled and failed requests."""
from collections import Counter, deque
from email.utils import parsedate_to_datetime
import time
import threading
from functools import wraps


def locked(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with self.lock: return method(self,*args,**kwargs)
    return call


class Budget:
    def __init__(self, config, *, clock=time.monotonic):
        self.config,self.clock=config,clock
        self.entries=deque(maxlen=256)
        self.blocked_until=0.0
        self.stats=Counter()
        self.lock=threading.RLock()

    @locked
    def prune(self):
        now=self.clock()
        while self.entries and now-self.entries[0]['time']>=60: self.entries.popleft()

    @locked
    def reserve(self, estimate, *, priority):
        self.prune()
        if self.clock()<self.blocked_until:
            self.stats['backoff_denied']+=1
            return None
        maximum=self.config.requests_per_minute
        if priority>3: maximum-=self.config.reserved_requests
        token_limit=self.config.tokens_per_minute-(self.config.reserved_tokens if priority>3 else 0)
        if len(self.entries)>=maximum or sum(item['tokens'] for item in self.entries)+estimate>token_limit:
            self.stats['budget_denied']+=1
            return None
        entry={'time':self.clock(),'tokens':estimate}
        self.entries.append(entry)
        self.stats['requests']+=1
        return entry

    @locked
    def settle(self, entry, usage):
        if usage:
            incoming=max(0,int(usage.get('prompt_tokens',0)))
            outgoing=max(0,int(usage.get('completion_tokens',0)))
            total=max(incoming+outgoing,int(usage.get('total_tokens',0)))
            entry['tokens']=total
            self.stats.update({'input_tokens':incoming,'output_tokens':outgoing,'measured_requests':1})
        else:
            self.stats['estimated_requests']+=1

    @locked
    def backoff(self, header=None, *, seconds=1):
        try:
            delay=float(header)
        except (TypeError,ValueError):
            try: delay=max(0,parsedate_to_datetime(header).timestamp()-time.time())
            except (TypeError,ValueError,OverflowError): delay=seconds
        # Retry-After is a lower bound; never retry early because a job has a short TTL.
        self.blocked_until=max(self.blocked_until,self.clock()+max(seconds,min(86400,delay)))

    @locked
    def snapshot(self):
        self.prune()
        return {'requests_window':len(self.entries),'tokens_window':sum(e['tokens'] for e in self.entries),
                'backoff_s':round(max(0,self.blocked_until-self.clock()),2),'stats':dict(self.stats)}
