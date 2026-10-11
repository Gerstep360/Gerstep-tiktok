"""Compatibility helper; actual deployment is handled by the install menu."""
from .nginx import blocks, attach


def insert_include(text, host='167.86.106.105'):
    candidates = [block for block in blocks(text) if block.name == 'server'
                  and any(values and (values[0] == '443' or values[0].endswith(':443')) for values in block.values('listen'))
                  and any(host in values for values in block.values('server_name'))]
    if len(candidates) != 1: raise ValueError('Se requiere un único servidor HTTPS con esa IP/dominio.')
    return attach(text, candidates[0], host)
