"""Attach one include to a uniquely identified HTTPS server, with tested rollback."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess

INCLUDE = 'include /etc/nginx/snippets/gerstep-interactive.conf;'


def insert_include(text, host='167.86.106.105'):
    if INCLUDE in text: return text
    tokens = list(re.finditer(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\#[^\n]*|[{};]|[^\s{};]+', text))
    candidates = []
    for index, token in enumerate(tokens[:-1]):
        if token.group() != 'server' or tokens[index+1].group() != '{': continue
        depth, end = 1, index + 2
        while end < len(tokens) and depth:
            value = tokens[end].group()
            if value == '{': depth += 1
            elif value == '}': depth -= 1
            end += 1
        if depth: raise ValueError('Nginx config has unbalanced braces.')
        block = text[tokens[index+1].end():tokens[end-1].start()]
        if re.search(r'\blisten\s+[^;]*\b443\b',block) and re.search(r'\bserver_name\s+[^;]*\b'+re.escape(host)+r'(?=\s|;)',block):
            if re.search(r'\blocation\s+[^\n{]*[/]Gerstep',block): raise ValueError('/Gerstep already has a location. Review it before attaching.')
            candidates.append(tokens[end-1].start())
    if len(candidates) != 1: raise ValueError('Select a site with exactly one HTTPS server_name 167.86.106.105. Otherwise add the include manually to the desired server block.')
    offset = candidates[0]
    return text[:offset] + '    ' + INCLUDE + '\n' + text[offset:]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('site')
    args = parser.parse_args()
    path = Path(args.site).resolve()
    if not path.is_relative_to(Path('/etc/nginx')) or not path.is_file(): raise SystemExit('Site must be an existing file inside /etc/nginx.')
    original = path.read_text()
    candidate = insert_include(original)
    if candidate != original:
        backup = path.with_name(path.name + '.gerstep-backup')
        if backup.exists(): raise SystemExit('Backup already exists. Review the previous installation first.')
        shutil.copy2(path,backup)
        path.write_text(candidate)
        test = subprocess.run(['nginx','-t'],capture_output=True,text=True)
        if test.returncode:
            path.write_text(original)
            raise SystemExit('Nginx validation failed; original configuration restored.\n' + test.stderr)
    print('Nginx site validated. Other server blocks were preserved.')
