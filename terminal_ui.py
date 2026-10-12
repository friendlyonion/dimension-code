"""Compact, Muse-inspired terminal presentation for Dimension."""
from __future__ import annotations

import difflib
from contextlib import contextmanager
import json
import os
import sys
import threading
import time
import urllib.request
try:
    import readline  # enables arrow-key editing and history for input()
except ImportError:
    pass
try:
    import termios
    import tty
except ImportError:
    termios = tty = None


class TerminalUI:
    def __init__(self, stream=None, *, color=None):
        self.stream = stream or sys.stdout
        self.color = (self.stream.isatty() and 'NO_COLOR' not in os.environ) if color is None else color
        self._render_lock = threading.RLock()
        self._booted = False
        self.models: list[str] = []
        self._input_history: list[str] = []
        self._memory_url: str | None = None
        self._memory_model = ''
        self._memory_cache = 'Mem —'
        self._memory_checked = 0.0

    def set_memory_source(self, endpoint: str, model: str) -> None:
        """Use Ollama's loaded-model stats when the endpoint exposes them."""
        base = endpoint.rstrip('/')
        if base.endswith('/v1'):
            base = base[:-3]
        self._memory_url = base + '/api/ps'
        self._memory_model = model
        self._memory_cache = 'Mem —'
        self._memory_checked = 0.0

    def _memory_status(self) -> str:
        now = time.monotonic()
        if self._memory_url and now - self._memory_checked >= 1.5:
            self._memory_checked = now
            try:
                request = urllib.request.Request(self._memory_url, headers={'Accept': 'application/json'})
                with urllib.request.urlopen(request, timeout=.25) as response:
                    models = json.loads(response.read(256_000)).get('models', [])
                current = next((item for item in models
                                if self._memory_model.casefold() in {
                                    str(item.get('name', '')).casefold(),
                                    str(item.get('model', '')).casefold()}), None)
                if current:
                    total = max(0, int(current.get('size', 0)))
                    vram = max(0, int(current.get('size_vram', 0)))
                    gib = 1024 ** 3
                    self._memory_cache = f'Mem {total / gib:.1f} GiB · VRAM {vram / gib:.1f} GiB'
                else:
                    self._memory_cache = 'Mem —'
            except (OSError, ValueError, TypeError, AttributeError):
                self._memory_cache = 'Mem unavailable'
        return self._memory_cache

    def set_models(self, models: list[str]) -> None:
        self.models = list(models)

    def _gradient(self, value: str) -> str:
        if not self.color:
            return value
        colors = ((132, 76, 255), (205, 91, 255), (77, 208, 255))
        chars = []
        for i, char in enumerate(value):
            section = min(1, i / max(1, len(value) - 1))
            left, right = colors[0:2] if section <= .5 else colors[1:3]
            portion = section * 2 if section <= .5 else (section - .5) * 2
            rgb = tuple(round(a + (b - a) * portion) for a, b in zip(left, right))
            chars.append(f'\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{char}')
        return ''.join(chars) + '\033[0m'

    def ink(self, value: str, code: str) -> str:
        return f'\033[{code}m{value}\033[0m' if self.color else value

    def line(self, icon: str, label: str, detail: str = '', tone: str = 'muted') -> None:
        colors = {'violet': '38;2;187;111;255', 'cyan': '38;2;42;207;220',
                  'green': '38;2;81;214;154', 'red': '38;2;255;111;128',
                  'muted': '38;2;155;163;190'}
        mark = self.ink(icon, colors.get(tone, colors['muted']))
        label = self.ink(label, '1;38;2;200;205;229')
        suffix = self.ink(' · ' + detail, '38;2;123;132;163') if detail else ''
        print(f'  {mark} {label}{suffix}', file=self.stream, flush=True)

    def header(self, repo: Path, model: str, test: str | None = None) -> None:
        self.boot()
        print(file=self.stream)
        width = min(76, max(48, shutil_terminal_width(self.stream) - 4))
        edge = self.ink('╭' + '─' * (width - 2) + '╮', '38;2;86;66;127')
        print('  ' + edge, file=self.stream)
        title = '  D I M E N S I O N'
        subtitle = '  /  local coding agent'
        padding = max(1, width - (1 + len(title) + len(subtitle) + 1))
        print('  ' + self.ink('│', '38;2;86;66;127') + self._gradient(title) +
              self.ink(subtitle, '38;2;144;151;180') +
              self.ink(' ' * padding + '│', '38;2;86;66;127'), file=self.stream)
        print('  ' + self.ink('├' + '─' * (width - 2) + '┤', '38;2;86;66;127'), file=self.stream)
        self.line('◈', 'WORKSPACE', str(repo), 'violet')
        self.line('◉', 'MODEL', model, 'cyan')
        if test:
            self.line('✓', 'CHECK', test, 'green')
        print('  ' + self.ink('╰' + '─' * (width - 2) + '╯', '38;2;86;66;127'), file=self.stream)
        print(file=self.stream, flush=True)

    def boot(self, duration: float = .42) -> None:
        """Play a tiny, non-blocking-in-spirit startup flourish before input."""
        if self._booted:
            return
        self._booted = True
        if not self.color or not getattr(self.stream, 'isatty', lambda: False)():
            return
        frames = ('◌', '◔', '◑', '◕', '●')
        start = time.monotonic()
        frame = 0
        while time.monotonic() - start < duration:
            with self._render_lock:
                self.stream.write('\r  ' + self.ink(frames[frame % len(frames)], '1;38;2;190;105;255') +
                                  self.ink('  Warming up Dimension…', '38;2;144;151;180') + '\033[K')
                self.stream.flush()
            frame += 1
            time.sleep(.07)
        with self._render_lock:
            self.stream.write('\r\033[2K')
            self.stream.flush()

    @contextmanager
    def activity(self, label: str):
        """Show an animated status line while work runs, then clear it cleanly."""
        if not self.color or not getattr(self.stream, 'isatty', lambda: False)():
            yield
            return

        stop = threading.Event()
        start = time.monotonic()
        frames = ('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')

        def animate():
            frame = 0
            while not stop.is_set():
                elapsed = time.monotonic() - start
                seconds = f'{elapsed:4.1f}s'
                memory = self._memory_status()
                with self._render_lock:
                    self.stream.write('\r  ' + self.ink(frames[frame % len(frames)], '1;38;2;190;105;255') +
                                      ' ' + self.ink(label, '1;38;2;205;210;230') +
                                      self.ink('  ·  ' + seconds + '  ·  ' + memory,
                                               '38;2;126;135;164') + '\033[K')
                    self.stream.flush()
                frame += 1
                stop.wait(.09)

        thread = threading.Thread(target=animate, daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=.5)
            with self._render_lock:
                self.stream.write('\r\033[2K')
                self.stream.flush()

    def plan(self, milestones: list[dict]) -> None:
        self.line('▰', 'PLAN', f'{len(milestones)} milestones', 'violet')
        for number, item in enumerate(milestones, 1):
            goal = str(item.get('goal', 'work')).replace('\n', ' ')[:100]
            rail = self.ink('●', '38;2;190;105;255') + self.ink(' ━ ', '38;2;83;72;112')
            print('  ' + rail + self.ink(f'{number:02d}', '1;38;2;210;190;255') +
                  self.ink('  ' + goal, '38;2;164;172;198'), file=self.stream)
        print(file=self.stream, flush=True)

    def write(self, path: str, before: str, after: str) -> None:
        removed = sum(1 for line in difflib.ndiff(before.splitlines(), after.splitlines()) if line.startswith('- '))
        added = sum(1 for line in difflib.ndiff(before.splitlines(), after.splitlines()) if line.startswith('+ '))
        self.line('◆', f'Edited {path}', f'+{added} −{removed}', 'violet')
        lines = list(difflib.unified_diff(before.splitlines(), after.splitlines(), n=1, lineterm=''))
        changed = [line for line in lines[2:] if line.startswith(('+', '-'))]
        visible = changed[:10]
        for value in visible:
            addition = value.startswith('+')
            shade = '48;2;19;59;40;38;2;126;232;179' if addition else '48;2;66;29;43;38;2;255;153;170'
            print('    ' + self.ink(value[:140].ljust(66), shade), file=self.stream)
        if len(changed) > len(visible):
            print(self.ink(f'    … {len(changed) - len(visible)} more changed lines', '38;2;112;121;147'), file=self.stream)
        self.stream.flush()

    def check(self, command: str, ok: bool, elapsed: float) -> None:
        display = 'Project syntax' if 'project_check.py' in command else command
        self.line('◆' if ok else '✕', 'Ran check',
                  f'{display} · {"✓" if ok else "failed"} · {elapsed:.1f}s',
                  'cyan' if ok else 'red')

    def failure(self, number: int, maximum: int, detail: str) -> None:
        self.line('◆', f'Fix attempt {number}/{maximum}', detail.replace('\n', ' ')[:180], 'red')

    def checkpoint(self, number: int, sha: str, goal: str) -> None:
        self.line('✦', f'MILESTONE {number} COMPLETE', f'{goal} · checkpoint {sha[:8]}', 'green')

    def rollback(self, sha: str) -> None:
        self.line('↶', 'Backtracked', f'restored {sha[:8]}; replanning this milestone', 'violet')

    def notice(self, label: str, detail: str = '') -> None:
        self.line('◆', label, detail, 'cyan')

    def error(self, message: str) -> None:
        self.line('✕', 'Error', message, 'red')

    def answer(self, message: str) -> None:
        self.line('◆', 'Answer', tone='violet')
        for paragraph in message.strip().splitlines():
            print('    ' + paragraph[:500], file=self.stream)
        print(file=self.stream, flush=True)

    def model_menu(self, models: list[str], current: str) -> None:
        self.line('◉', 'INSTALLED LOCAL MODELS', f'{len(models)} found', 'cyan')
        if models:
            for index, name in enumerate(models, 1):
                marker = '●' if name == current else '○'
                self.line(marker, f'{index:>2}  {name}', 'current' if name == current else '',
                          'violet' if name == current else 'muted')
        else:
            self.line('!', 'No local Ollama models found', 'run `Dimension --setup` or `ollama pull MODEL`', 'red')

    def help_menu(self) -> None:
        self.line('?', 'DIMENSION COMMANDS', tone='violet')
        commands = (
            ('/help', 'Show this command guide'),
            ('/models', 'List models installed in local Ollama'),
            ('/model NAME', 'Switch to an installed local model'),
            ('/context', 'Show the current context window'),
            ('/context VALUE', 'Set and save context tokens (512–131072)'),
            ('/requests', 'List saved requests and their progress'),
            ('/resume', 'Resume the latest unfinished request'),
            ('/exit', 'Quit Dimension'),
            ('Anything else', 'Ask a project question or describe a code change'),
        )
        for command, description in commands:
            print('    ' + self.ink(f'{command:<18}', '1;38;2;190;120;255') +
                  self.ink(description, '38;2;159;168;194'), file=self.stream)
        print(file=self.stream, flush=True)

    def footer(self, model: str, repo: Path) -> None:
        width = min(76, max(48, shutil_terminal_width(self.stream) - 4))
        print('  ' + self.ink('─' * width, '38;2;66;70;85'), file=self.stream)
        left = self.ink(f'◆ {model}', '38;2;190;105;255')
        right = self.ink(f'{repo.name}  ·  green checkpoints', '38;2;125;134;163')
        print('  ' + left + '  ' + self.ink('│', '38;2;78;82;104') + '  ' + right,
              file=self.stream, flush=True)

    def prompt(self, label: str = '') -> str:
        if label:
            print('  ' + self.ink(label, '38;2;136;145;174'), file=self.stream)
        if termios is not None and tty is not None and sys.stdin.isatty() and self.stream.isatty():
            value = self._interactive_prompt()
        else:
            value = input('  ' + self.ink('❯', '1;38;2;185;101;255') + ' ')
        if value.strip() and 'readline' in globals():
            readline.add_history(value)
        if value.strip() and (not self._input_history or self._input_history[-1] != value):
            self._input_history.append(value)
        return value

    def _suggestions(self, text: str) -> list[tuple[str, str]]:
        commands = [('/help', 'command guide'), ('/models', 'installed local models'),
                    ('/model ', 'switch model'), ('/context', 'show context window'),
                    ('/context ', 'set context tokens'), ('/requests', 'saved request progress'),
                    ('/resume', 'resume latest unfinished request'), ('/exit', 'quit Dimension')]
        if text.startswith('/model '):
            prefix = text[len('/model '):]
            return [(f'/model {name}', 'switch model') for name in self.models
                    if name.startswith(prefix) and name != prefix]
        if text.startswith('/context '):
            prefix = text[len('/context '):]
            return [(f'/context {size}', 'context size') for size in
                    ('4096', '8192', '16384', '32768', '65536')
                    if size.startswith(prefix) and size != prefix]
        if not text.startswith('/'):
            return []
        return [(command, description) for command, description in commands
                if command.startswith(text) and command != text]

    def _interactive_prompt(self) -> str:
        """Single-line editor with a live slash-command picker and arrow navigation."""
        prompt = '  ' + self.ink('❯', '1;38;2;185;101;255') + ' '
        fd = sys.stdin.fileno()
        previous = termios.tcgetattr(fd)
        text = ''
        cursor = 0
        selected = 0
        history_index = len(self._input_history)
        suggestions: list[tuple[str, str]] = []

        def redraw():
            nonlocal suggestions, selected
            suggestions = self._suggestions(text)
            selected = min(selected, max(0, len(suggestions) - 1))
            self.stream.write('\r\033[2K' + prompt + text)
            if cursor < len(text):
                self.stream.write(f'\033[{len(text) - cursor}D')
            self.stream.write('\033[s\033[J')
            if suggestions:
                for index, (command, description) in enumerate(suggestions[:8]):
                    marker = '❯' if index == selected else ' '
                    tone = '48;2;54;35;78;38;2;230;196;255' if index == selected else '38;2;145;153;180'
                    self.stream.write('\r\n  ' + self.ink(marker, '38;2;190;105;255') + ' ' +
                                      self.ink(f'{command:<22}', tone) +
                                      self.ink(description, '38;2;123;132;157'))
            self.stream.write('\033[u')
            self.stream.flush()

        tty.setraw(fd)
        try:
            self.stream.write(prompt)
            self.stream.flush()
            while True:
                char = sys.stdin.read(1)
                if char in ('\r', '\n'):
                    if suggestions:
                        text = suggestions[selected][0]
                        cursor = len(text)
                        suggestions = []
                        redraw()
                        continue
                    self.stream.write('\r\033[2K' + prompt + text + '\r\n')
                    self.stream.flush()
                    return text
                if char == '\x03':
                    self.stream.write('\r\033[2K\r\n')
                    self.stream.flush()
                    raise KeyboardInterrupt
                if char == '\x04':
                    if not text:
                        raise EOFError
                    continue
                if char == '\x1b':
                    seq = sys.stdin.read(2)
                    if seq == '[A':
                        if suggestions:
                            selected = (selected - 1) % len(suggestions)
                        elif self._input_history and history_index > 0:
                            history_index -= 1
                            text = self._input_history[history_index]
                            cursor = len(text)
                    elif seq == '[B':
                        if suggestions:
                            selected = (selected + 1) % len(suggestions)
                        elif history_index < len(self._input_history):
                            history_index += 1
                            text = self._input_history[history_index] if history_index < len(self._input_history) else ''
                            cursor = len(text)
                    elif seq == '[D':
                        cursor = max(0, cursor - 1)
                    elif seq == '[C':
                        cursor = min(len(text), cursor + 1)
                    redraw()
                    continue
                if char in ('\x7f', '\x08'):
                    if cursor:
                        text = text[:cursor - 1] + text[cursor:]
                        cursor -= 1
                elif char == '\t':
                    if suggestions:
                        text = suggestions[selected][0]
                        cursor = len(text)
                elif char.isprintable():
                    text = text[:cursor] + char + text[cursor:]
                    cursor += len(char)
                redraw()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def shutil_terminal_width(stream) -> int:
    try:
        return os.get_terminal_size(stream.fileno()).columns
    except (OSError, AttributeError, ValueError):
        return 80
