"""Parse loaded Nginx files without touching unrelated virtual hosts."""
from dataclasses import dataclass
from pathlib import Path
import re

TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\#[^\n]*|[{};]|[^\s{};]+')
INCLUDE = 'include /etc/nginx/snippets/gerstep-interactive.conf;'
HTTP_INCLUDE = 'include /etc/nginx/gerstep-interactive-http.conf;'
CHALLENGE = 'location ^~ /.well-known/acme-challenge/ { root /var/lib/gerstep-interactive/acme; }'


@dataclass
class Block:
    name: str
    start: int
    opening: int
    closing: int
    directives: list
    path: Path = None

    def values(self, name): return [values for key, values, _, _ in self.directives if key == name]


def blocks(text):
    tokens = [m for m in TOKEN.finditer(text) if not m.group().startswith('#')]
    found = []
    for index, token in enumerate(tokens[:-1]):
        if token.group() not in {'http', 'server'} or tokens[index + 1].group() != '{': continue
        depth, cursor, start, directives = 1, index + 2, index + 2, []
        while cursor < len(tokens) and depth:
            value = tokens[cursor].group()
            if value == '{': depth += 1
            elif value == '}':
                depth -= 1
                if depth == 1: start = cursor + 1
            elif value == ';' and depth == 1:
                parts = [t.group().strip('\"\'') for t in tokens[start:cursor]]
                if parts: directives.append((parts[0], parts[1:], tokens[start].start(), tokens[cursor].end()))
                start = cursor + 1
            cursor += 1
        if depth: raise ValueError('Nginx contiene llaves sin cerrar.')
        found.append(Block(token.group(), token.start(), tokens[index + 1].end(), tokens[cursor - 1].start(), directives))
    return found


def loaded_files(dump):
    paths = re.findall(r'^# configuration file (.+):$', dump, re.M)
    result = {}
    for name in paths:
        path = Path(name).resolve()
        # These paths come from Nginx itself, never from browser inputs.
        if path.is_file(): result[path] = path.read_text()
    if not result: raise ValueError('No se pudieron identificar los archivos de Nginx.')
    return result


def servers(files, port):
    result = []
    for path, text in files.items():
        for block in blocks(text):
            if block.name != 'server': continue
            listens = block.values('listen')
            if any(values and (values[0] == str(port) or values[0].endswith(':' + str(port))) for values in listens):
                block.path = path
                result.append(block)
    return result


def choose(items, host, ui):
    exact = [b for b in items if any(host in values for values in b.values('server_name'))]
    candidates = exact or [b for b in items if any('default_server' in values for values in b.values('listen'))] or items
    if len(candidates) == 1: return candidates[0]
    if not candidates: return None
    ui.say('Hay varios servidores posibles. Elegí dónde añadir únicamente /Gerstep:')
    for i, block in enumerate(candidates, 1): ui.say(f'{i}. {block.path} — {block.values("server_name")}')
    value = ui.ask('Servidor', '1')
    if not value.isdecimal() or not 1 <= int(value) <= len(candidates): raise ValueError('Selección inválida.')
    return candidates[int(value) - 1]


def attach(text, block, host, directive=INCLUDE):
    body = text[block.opening:block.closing]
    body_code = ' '.join(m.group() for m in TOKEN.finditer(body) if not m.group().startswith('#'))
    included = (['/etc/nginx/snippets/gerstep-interactive.conf'] in block.values('include')
                if directive == INCLUDE else ' '.join(m.group() for m in TOKEN.finditer(directive)) in body_code)
    if directive == INCLUDE and not included and re.search(r'\blocation\s+[^\n{]*[/]Gerstep', body_code):
        raise ValueError('/Gerstep ya está configurado por otra instalación.')
    edits = [] if included else [(block.closing, block.closing, '\n    ' + directive + '\n')]
    # Server rewrites (including return inside if/include) run BEFORE location
    # lookup. Skip that phase only for our route; leave other applications intact.
    pattern = '^/Gerstep(/|$)' if directive == INCLUDE else '^/\\.well-known/acme-challenge/'
    bypass = f'if ($uri ~ "{pattern}") {{ break; }}'
    bypass_code = ' '.join(m.group() for m in TOKEN.finditer(bypass))
    if bypass_code not in body_code:
        edits.append((block.opening, block.opening, '\n    # Gerstep: bypass server rewrites only for its own route.\n    ' + bypass + '\n'))
    names = [d for d in block.directives if d[0] == 'server_name']
    if not any(host in d[1] for d in names):
        if names:
            name = names[0]
            edits.append((name[2], name[3], 'server_name ' + ' '.join([*name[1], host]) + ';'))
        else: edits.append((block.opening, block.opening, '\n    server_name ' + host + ';\n'))
    for begin, end, replacement in sorted(edits, reverse=True): text = text[:begin] + replacement + text[end:]
    return text


def http_include(files):
    for path, text in files.items():
        for block in blocks(text):
            if block.name == 'http':
                if ['/etc/nginx/gerstep-interactive-http.conf'] not in block.values('include'):
                    return path, text[:block.opening] + '\n    ' + HTTP_INCLUDE + '\n' + text[block.opening:]
                return path, text
    raise ValueError('No se encontró el bloque http de Nginx.')
