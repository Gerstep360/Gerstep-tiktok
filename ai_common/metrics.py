import math
import statistics


def distribution(values):
    values=sorted(values)
    return {'samples':len(values),'median_ms':round(statistics.median(values),2) if values else None,
            'p95_ms':round(values[max(0,math.ceil(.95*len(values))-1)],2) if values else None}
