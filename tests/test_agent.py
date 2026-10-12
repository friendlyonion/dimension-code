import tempfile
import unittest
from pathlib import Path
import subprocess
import sys
import json
from io import BytesIO, StringIO
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Model, answer_question, bootstrap_repository, distill, failure_context, fallback_check, git, is_question, license_flag, read_file, repo_map, run, safe_path, search_files, suggest_check, validate_pyproject
from terminal_ui import TerminalUI


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.name = 'test-model'

    def ask(self, system, user):
        return next(self.responses)


class AgentTests(unittest.TestCase):
    def test_terminal_ui_shows_brand_and_compact_diff(self):
        output = StringIO()
        ui = TerminalUI(output, color=False)
        ui.header(Path('/tmp/example'), 'qwen3.5:9b', 'python3 -m unittest')
        ui.write('hello.py', '', 'print("hello")\n')
        ui.check('python3 -m unittest', True, 0.4)
        view = output.getvalue()
        self.assertIn('D I M E N S I O N', view)
        self.assertIn('◉ MODEL', view)
        self.assertIn('Edited hello.py', view)
        self.assertIn('+print("hello")', view)
        self.assertIn('0.4s', view)
        self.assertNotIn('\033[', view)

    def test_question_answers_without_git_or_check(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / 'README.md').write_text('# Keymaster\nA password manager.\n')
            output = StringIO()
            model = FakeModel([{'answer': 'It manages passwords.'}])
            self.assertTrue(is_question('What does this repo do'))
            self.assertFalse(is_question('Add a login form'))
            self.assertEqual(answer_question(repo, 'What does this repo do', model,
                                             TerminalUI(output, color=False)),
                             'It manages passwords.')
            self.assertIn('It manages passwords.', output.getvalue())
            self.assertFalse((repo / '.git').exists())

    def test_suggest_check_uses_project_configuration(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / 'package.json').write_text('{"scripts":{"test":"vitest run"}}')
            self.assertEqual(suggest_check(repo), 'npm test')

    def test_search_finds_large_file_line_for_targeted_edit(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / 'popup.js').write_text('// filler\n' * 5000 + 'const recording = false;\n')
            self.assertIn('popup.js:5001:', search_files(repo, 'recording'))

    def test_fallback_check_and_natural_edit_request(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / 'background.js').write_text('const recording = false;\n')
            self.assertIsNone(suggest_check(repo))
            check = fallback_check(repo)
            self.assertTrue(subprocess.run(__import__('shlex').split(check), capture_output=True).returncode == 0)
            self.assertFalse(is_question('okay cool can we add a network traffic capturer?'))
            (repo / 'background.js').write_text('const = ;\n')
            self.assertNotEqual(subprocess.run(__import__('shlex').split(check), capture_output=True).returncode, 0)

    def test_replace_action_can_edit_large_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            git(repo, 'config', 'user.name', 'Test')
            git(repo, 'config', 'user.email', 'test@example.invalid')
            large = '// filler placeholder\n' * 2800 + 'const recording = false;\n'
            (repo / 'background.js').write_text(large)
            git(repo, 'add', 'background.js')
            git(repo, 'commit', '-qm', 'baseline')
            self.assertIn('recording', read_file(repo, 'background.js', 2801, 2801))
            model = FakeModel([{'milestones': [{'goal': 'record', 'done': 'syntax'},
                                                {'goal': 'status', 'done': 'syntax'},
                                                {'goal': 'finish', 'done': 'syntax'}]},
                               {'action': 'read', 'path': 'background.js', 'start_line': 2801, 'end_line': 2801},
                               {'action': 'replace', 'path': 'background.js',
                                'old': 'const recording = false;', 'new': 'const recording = true;'},
                               {'action': 'write', 'files': {'status.txt': 'ready'}},
                               {'action': 'write', 'files': {'done.txt': 'done'}}])
            self.assertEqual(run(repo, 'add recording', fallback_check(repo), model,
                                 max_steps=5), 0)
            self.assertIn('const recording = true;', (repo / 'background.js').read_text())

    def test_inspection_limit_blocks_more_reads_and_allows_edit_retry(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            git(repo, 'config', 'user.name', 'Test')
            git(repo, 'config', 'user.email', 'test@example.invalid')
            (repo / 'background.js').write_text('const recording = false;\n')
            (repo / 'notes.txt').write_text('\n'.join(f'note {line}' for line in range(1, 9)) + '\n')
            git(repo, 'add', 'background.js', 'notes.txt')
            git(repo, 'commit', '-qm', 'baseline')
            plan = {'milestones': [{'goal': f'edit {number}', 'done': 'syntax'}
                                   for number in range(1, 4)]}
            reads = [{'action': 'read', 'path': 'background.js', 'start_line': 1, 'end_line': 1}]
            reads.extend({'action': 'read', 'path': 'notes.txt', 'start_line': line, 'end_line': line}
                         for line in range(1, 8))
            responses = [plan, *reads,
                         {'action': 'read', 'path': 'notes.txt', 'start_line': 8, 'end_line': 8},
                         {'action': 'read', 'path': 'background.js', 'start_line': 1, 'end_line': 1},
                         {'action': 'replace', 'path': 'background.js',
                          'old': 'const recording = false;', 'new': 'const recording = true;'},
                         {'action': 'write', 'files': {'status.txt': 'recording ready'}},
                         {'action': 'write', 'files': {'done.txt': 'done'}}]
            output = StringIO()
            self.assertEqual(run(repo, 'add traffic recording', fallback_check(repo),
                                 FakeModel(responses), max_steps=15,
                                 ui=TerminalUI(output, color=False)), 0)
            self.assertIn('const recording = true;', (repo / 'background.js').read_text())
            self.assertIn('Read blocked', output.getvalue())

    def test_bootstrap_creates_private_remote_without_push(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / 'my-project'
            repo.mkdir()
            (repo / 'app.py').write_text('print("hi")\n')
            (repo / '.env').write_text('SECRET=test\n')
            actual_run = subprocess.run
            calls = []
            def fake_run(args, **kwargs):
                if args[0] == 'gh':
                    calls.append(args)
                    return subprocess.CompletedProcess(args, 0, stdout='https://github.com/test/my-project\n')
                return actual_run(args, **kwargs)
            with patch('agent.subprocess.run', side_effect=fake_run), \
                 patch('agent.shutil.which', return_value='/usr/bin/gh'):
                self.assertTrue(bootstrap_repository(repo))
            create = calls[-1]
            self.assertEqual(create[:4], ['gh', 'repo', 'create', 'my-project'])
            self.assertIn('--private', create)
            self.assertNotIn('--push', create)
            self.assertEqual(git(repo, 'status', '--porcelain'), '')
            self.assertEqual(git(repo, 'ls-files'), 'app.py')

    def test_bootstrap_invalid_login_does_not_initialize_git(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            with patch('agent.shutil.which', return_value='/usr/bin/gh'), \
                 patch('agent.subprocess.run') as command:
                command.side_effect = [subprocess.CompletedProcess([], 128),
                                       subprocess.CompletedProcess([], 1)]
                with self.assertRaisesRegex(RuntimeError, 'GitHub login has expired'):
                    bootstrap_repository(repo)
            self.assertFalse((repo / '.git').exists())

    def test_ollama_request_uses_qwen_and_bounded_context(self):
        seen = {}
        def fake_urlopen(request, timeout):
            seen['path'] = request.full_url
            seen['body'] = json.loads(request.data)
            return BytesIO(json.dumps({'message': {'content': '{"action":"done","summary":"ok"}'}}).encode())
        with patch('urllib.request.urlopen', side_effect=fake_urlopen):
            response = Model('http://127.0.0.1:11435', 'qwen3.5:9b').ask('system', 'user')
        self.assertEqual(response['action'], 'done')
        self.assertEqual(seen['path'], 'http://127.0.0.1:11435/api/chat')
        self.assertEqual(seen['body']['model'], 'qwen3.5:9b')
        self.assertEqual(seen['body']['options']['num_ctx'], 4096)
        self.assertEqual(seen['body']['options']['num_predict'], 1536)
        self.assertFalse(seen['body']['think'])

    def test_on_demand_read_is_line_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'source.py').write_text('one\ntwo\nthree\n')
            self.assertEqual(read_file(root, 'source.py', 2, 3), '2: two\n3: three')
            with self.assertRaises(ValueError):
                read_file(root, 'source.py', 1, 1000)

    def test_failure_context_shows_test_and_implementation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            (root / 'tests').mkdir()
            (root / 'tests' / 'test_cli.py').write_text('assert output == "ok"\n')
            (root / 'cli.py').write_text('print("ok")\n')
            log = f'File "{root / "tests" / "test_cli.py"}", line 1\nAssertionError'
            context = failure_context(root, log, set())
            self.assertIn('tests/test_cli.py', context)
            self.assertIn('cli.py', context)

    def test_repo_map_uses_signatures_and_docstrings(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'a.py').write_text('def add(a, b):\n    """Return sum."""\n    return a + b\n')
            result = repo_map(Path(d))
            if result.startswith('Tree-sitter unavailable'):
                self.skipTest('optional Tree-sitter packages absent')
            self.assertIn('def add(a, b):', result)
            self.assertIn('Return sum.', result)
            self.assertNotIn('return a + b', result)

    def test_safe_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertEqual(safe_path(root, 'src/a.py'), root.resolve() / 'src/a.py')
            for bad in ('../outside', '/tmp/outside', '.git/config'):
                with self.assertRaises(ValueError):
                    safe_path(root, bad)

    def test_distill(self):
        self.assertEqual(distill('noise\nERROR failed\nmore noise'), 'ERROR failed')

    def test_license_flags(self):
        self.assertEqual(license_flag('MIT'), 'preferred')
        self.assertIn('GPL', license_flag('GPL-3.0'))
        self.assertEqual(license_flag('NOASSERTION'), 'review license')

    def test_console_entry_point_validation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'pyproject.toml').write_text('[project.scripts]\ncalc = "calculator.cli:main"\n')
            self.assertIn('missing module', validate_pyproject(root))
            (root / 'cli.py').write_text('def main():\n    pass\n')
            (root / 'pyproject.toml').write_text('[project.scripts]\ncalc = "cli:main"\n')
            self.assertEqual(validate_pyproject(root), '')

    def test_five_failures_rollback_then_green_commit(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            git(repo, 'config', 'user.name', 'Test')
            git(repo, 'config', 'user.email', 'test@example.invalid')
            (repo / 'check.py').write_text("from pathlib import Path\np=Path('result.txt')\nassert not p.exists() or p.read_text() == 'good'\n")
            git(repo, 'add', 'check.py')
            git(repo, 'commit', '-qm', 'baseline')
            first = git(repo, 'rev-parse', 'HEAD')
            responses = [{'milestones': [{'goal': 'make result', 'done': 'green'},
                                         {'goal': 'verify result', 'done': 'green'},
                                         {'goal': 'finish', 'done': 'green'}]}]
            responses += [{'action': 'write', 'files': {'result.txt': 'bad'}} for _ in range(5)]
            responses += [{'goal': 'make result with corrected value', 'done': 'green'}]
            responses += [{'action': 'write', 'files': {'result.txt': 'good'}},
                          {'action': 'write', 'files': {'m2.txt': 'green'}},
                          {'action': 'write', 'files': {'m3.txt': 'green'}}]
            rc = run(repo, 'make result', f'{sys.executable} check.py', FakeModel(responses),
                     max_steps=8)
            self.assertEqual(rc, 0)
            self.assertEqual((repo / 'result.txt').read_text(), 'good')
            self.assertNotEqual(git(repo, 'rev-parse', 'HEAD'), first)
            self.assertEqual(git(repo, 'status', '--porcelain'), '')
            self.assertEqual(git(repo, 'rev-list', '--count', 'HEAD'), '4')

    def test_green_commit_includes_prior_failed_edit(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            git(repo, 'config', 'user.name', 'Test')
            git(repo, 'config', 'user.email', 'test@example.invalid')
            (repo / 'check.py').write_text("from pathlib import Path\na=Path('a.txt'); b=Path('b.txt')\nassert not a.exists() or b.exists()\n")
            git(repo, 'add', 'check.py')
            git(repo, 'commit', '-qm', 'baseline')
            responses = [{'milestones': [{'goal': 'first', 'done': 'green'},
                                         {'goal': 'second', 'done': 'green'},
                                         {'goal': 'third', 'done': 'green'}]},
                         {'action': 'write', 'files': {'a.txt': 'bad'}},
                         {'action': 'write', 'files': {'b.txt': 'good'}},
                         {'action': 'write', 'files': {'m2.txt': 'two'}},
                         {'action': 'write', 'files': {'m3.txt': 'three'}}]
            self.assertEqual(run(repo, 'create files', f'{sys.executable} check.py',
                                 FakeModel(responses), max_steps=5), 0)
            tracked = git(repo, 'show', '--pretty=format:', '--name-only', 'HEAD~2')
            self.assertIn('a.txt', tracked)
            self.assertIn('b.txt', tracked)

    def test_model_error_restores_last_green_state(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            git(repo, 'config', 'user.name', 'Test')
            git(repo, 'config', 'user.email', 'test@example.invalid')
            (repo / 'check.py').write_text("from pathlib import Path\nassert not Path('bad.txt').exists()\n")
            git(repo, 'add', 'check.py')
            git(repo, 'commit', '-qm', 'baseline')
            class FailingModel:
                count = 0
                def ask(self, system, user):
                    self.count += 1
                    if self.count == 1:
                        return {'milestones': [{'goal': str(i), 'done': 'green'} for i in range(3)]}
                    if self.count == 2:
                        return {'action': 'write', 'files': {'bad.txt': 'bad'}}
                    raise RuntimeError('model disconnected')
            with self.assertRaisesRegex(RuntimeError, 'model disconnected'):
                run(repo, 'test cleanup', f'{sys.executable} check.py', FailingModel())
            self.assertFalse((repo / 'bad.txt').exists())
            self.assertEqual(git(repo, 'status', '--porcelain'), '')


if __name__ == '__main__':
    unittest.main()
