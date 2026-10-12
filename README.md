# Dimension

Dimension is a terminal coding agent powered by local `qwen3.5:9b`. It gives the model one bounded edit at a time, runs a test command you choose, and commits every passing state. After five consecutive failed edits, it resets to the last green commit and asks the model to replan with the failure history.

## Start

The `Dimension` launcher is in `~/.local/bin`, which is on this Mac's `PATH`. It also works as `./Dimension` from this folder.

1. Install Ollama **0.22 or newer**. The `qwen3.5:9b` tag requires it. This Mac has Homebrew Ollama 0.40.2.
2. Run `Dimension --setup`. Dimension starts its own Ollama server on `127.0.0.1:11435` and downloads `qwen3.5:9b` into this folder's `.runtime/models` if needed.
3. Run `gh auth login -h github.com` if you want Dimension to create a GitHub repository for a folder that is not under Git. Run `Dimension`; on first launch, choose from installed Ollama models. Type a question or coding task at the purple `❯` prompt. Up arrow recalls previous prompts.

The terminal opens with a short animation and uses a purple-to-cyan wordmark, framed workspace panel, animated thinking/check spinner, milestone rail, concise edit diffs, check timings, green commits, and rollback events. During animated activity, the status line shows the loaded model's total memory and VRAM usage when the local endpoint supports Ollama's `/api/ps`; other compatible endpoints show memory as unavailable. Animation stays off the input line and falls back to plain transcript output when `NO_COLOR` is set or output is redirected.

Example:

```sh
cd /path/to/project
Dimension --test "python3 -m unittest discover -s tests"
```

At the prompt, ask `What does this repo do?` for a read-only answer or type `Create a CLI calculator with tests for arithmetic and division by zero.` for an edit. Questions do not initialize Git or run tests. For edits, Dimension selects an existing project check when it can. If none is found, it automatically checks Python, JavaScript, and JSON syntax. `--test` overrides the selection. The syntax fallback catches broken files but cannot establish that a feature works; add project tests for a stronger green checkpoint.

For one scripted task:

```sh
Dimension --repo /path/to/project \
  --task "Create a CLI calculator with tests" \
  --test "python3 -m unittest discover -s tests"
```

On the first task in a folder without Git, Dimension checks your GitHub CLI login, initializes Git, commits a local baseline, and creates an **empty private** repository on your GitHub account. It does not push your files. The local baseline excludes common credentials such as `.env` and private keys. You can inspect the files and run `git push -u origin HEAD` when you choose to publish them. Existing Git repositories are left as they are. If GitHub authentication has expired, Dimension asks you to refresh it before changing the folder.

Dimension uses Ollama's native chat API by default, with thinking disabled and a 4096-token context to control memory. `--context-size` changes that limit. Research runs by default; use `--no-research` when offline. To use another OpenAI compatible local server, supply `--endpoint http://127.0.0.1:1234/v1 --model model-name`.

Interactive commands: type `/` to open the live command picker, then use the up/down arrows to select a command and Enter to complete it. Tab also accepts the highlighted completion. `/help` lists commands, `/models` lists installed local models, `/model NAME` switches and saves the selected model, `/context` shows the current context window, `/context 8192` changes and saves its token limit, `/requests` lists saved tasks and progress, `/resume` resumes the latest unfinished task, and `/exit` quits. Context values must be from 512 to 131072 tokens. Model and context choices are saved under `.runtime/settings.json` in the Dimension installation. Use `--model NAME` or `--context-size TOKENS` to override a saved choice for a one-off run.

Each coding task is recorded as a Markdown file under `requests/` in that project folder. The note keeps the original request, plan, active milestone and step, recent progress, and last green Git checkpoint. Repeating the same unfinished request resumes it automatically; `/resume` picks up the most recently updated unfinished request. If a run was interrupted mid-edit, Dimension restores the saved checkpoint and removes only untracked files it recorded creating. Request notes are excluded from Git with the repository's local `.git/info/exclude`, so they stay on that machine and do not get committed or pushed.

## Agent loop

1. Verify a clean worktree and passing baseline.
2. Build a compact Tree-sitter map of Python, JavaScript, and TypeScript signatures and Python docstrings. The grammars are installed in `.runtime/python` on this Mac. Install `requirements-map.txt` if they are absent elsewhere.
3. Search GitHub and the web. The brief includes up to three candidate repositories, README sections, top-level layout, and license flags. MIT and Apache-2.0 are preferred; GPL is flagged for review. Research text is untrusted and no source code is copied automatically.
4. Ask the model for three to six milestones with done criteria. Each milestone advances after a passing edit and green commit. The fixed tests are the actual gate; the prose done criteria are not independently checked.
5. Let the model search for text, read bounded ranges on demand, write small complete files, and make targeted replacements in larger existing files. Existing files must be read before edits. Repeated reads are suppressed, and after eight inspection actions Dimension asks for a concrete edit. The model cannot choose shell commands.
6. Run the fixed test command after edits. Return error lines and stack traces rather than full logs.
7. Commit every passing state. After five failed edits, reset to the last green commit, remove only untracked files the agent created, and replan with all five distilled failures.
8. Carry short milestone summaries forward. The model context is capped.

## Safety and limits

- Use a dedicated folder and do not edit it concurrently. Rollback uses `git reset --hard` inside the target repository.
- The agent can overwrite files within that repository. Review commits before merging important work.
- Tests run locally with the command you provide. The model cannot change the command.
- Research snippets and repository contents may contain malicious instructions. Use trusted projects and review output.
- `qwen3.5:9b` is about 7.6 GB on disk in the default Ollama tag. On this 24 GB unified-memory Mac, a long inference session reached roughly 20 GiB peak memory. An 8 GB VRAM system may need CPU offload or the smaller official `qwen3.5:9b-q4_K_M` quantization, so full-speed 8 GB GPU operation is **not proven**.

## Verify

```sh
python3 -m unittest discover -s tests -v
Dimension --setup
```

The tests cover the read-only question path, automatic check selection, a syntax fallback for JavaScript projects, targeted edits in files over 40 KB, terminal output, private GitHub repository setup without a push, expired login handling, rollback after five failures, green commits, cleanup after model errors, bounded local API requests, path safety, Tree-sitter mapping, log distillation, license flags, and console entry-point validation. A live three-milestone `add(a,b)` task completed with `qwen3.5:9b` in `.runtime/demo3`. A fuller calculator in `.runtime/demo4` exercised research, all four operations, CLI tests, failure distillation, rollback, and replanning; its 11 tests pass. Manual review caught and corrected an invalid console entry point in the generated metadata. The harness now checks that target before committing new metadata.
