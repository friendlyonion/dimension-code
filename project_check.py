"""Dependency-free baseline syntax checks when a project has no test command."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys

SKIP = {'.git', '.venv', 'node_modules', 'dist', 'build', '__pycache__', '.runtime'}


def check(repo: Path) -> int:
    checked = 0
    failures = []
    for path in sorted(repo.rglob('*')):
        if not path.is_file() or any(part in SKIP for part in path.relative_to(repo).parts):
            continue
        if path.stat().st_size > 1_000_000:
            continue
        relative = path.relative_to(repo)
        try:
            if path.suffix == '.py':
                ast.parse(path.read_text(errors='replace'), filename=str(relative))
            elif path.suffix == '.json':
                json.loads(path.read_text(errors='replace'))
            elif path.suffix in {'.js', '.mjs', '.cjs'}:
                if not shutil.which('node'):
                    failures.append(f'{relative}: Node.js is required to check JavaScript syntax')
                    continue
                result = subprocess.run(['node', '--check', str(path)], capture_output=True, text=True,
                                        timeout=20)
                if result.returncode:
                    failures.append(f'{relative}: {result.stderr.strip()[-1200:]}')
                    continue
            else:
                continue
            checked += 1
        except (OSError, SyntaxError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
            failures.append(f'{relative}: {error}')
    for failure in failures:
        print(f'ERROR {failure}', file=sys.stderr)
    print(f'Checked syntax in {checked} source files.')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(check(Path(sys.argv[1]).resolve()))
