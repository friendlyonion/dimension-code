# Dimension

Dimension is a local coding agent that works inside your project from the terminal. Ask it what a codebase does or describe a change. It uses a local model, reads and edits project files, runs a check, and saves each passing milestone as a Git checkpoint. If repeated fixes fail, it returns to the last passing checkpoint and replans.

## Get started

Dimension uses [Ollama](https://ollama.com) by default. Install Ollama, then run:

```sh
./Dimension --setup
```

Setup starts Dimension's local Ollama service and downloads the default `qwen3.5:9b` model into `.runtime/`. On first launch, Dimension lists installed models so you can choose one. To use the command from anywhere, put this folder's `Dimension` launcher on your `PATH`.

Open a project and start Dimension:

```sh
cd /path/to/your/project
/path/to/Dimension-Code/Dimension
```

Then ask a question or describe a change:

```text
❯ What does this project do?
❯ Add a network traffic recorder with start and stop controls.
```

Questions are answered from the project without editing files. For a coding request, Dimension checks the project, researches related projects, makes a short milestone plan, edits files, and runs the selected check. You can set a check explicitly:

```sh
Dimension --test "python3 -m unittest discover -s tests"
```

## Terminal commands

Type `/` to open the command picker. Use the arrow keys to choose a command, Enter to run it, or Tab to complete it.

- `/help` — show commands
- `/models` — list installed local models
- `/model NAME` — switch models
- `/context` — show the context limit
- `/context 8192` — set the context limit
- `/requests` — view saved coding requests and progress
- `/resume` — resume the latest unfinished request
- `/exit` — quit

Dimension saves model and context preferences under `.runtime/`. Requests and progress notes are stored in a `requests/` folder in the project.

## Checkpoints and GitHub

Dimension creates a local Git checkpoint after each passing milestone. After five consecutive failed fixes, it restores the last green checkpoint and replans the milestone. Existing Git projects keep their current remote settings.

When used in a folder without Git, Dimension can create a local repository and an empty private GitHub repository using the GitHub CLI (`gh`). It commits a local baseline, excludes common secret files, and does not push project files. Review the baseline before publishing with Git.

## Models and local servers

The default Ollama context limit is 4096 tokens. Change it in the terminal with `/context VALUE`, or at launch with `--context-size VALUE`. To use another local OpenAI-compatible server:

```sh
Dimension --endpoint http://127.0.0.1:1234/v1 --model MODEL_NAME
```

Dimension can use small local models, though speed and code quality depend on the model, quantization, and hardware. A 9B model may need CPU offload on an 8 GB graphics card.

## Safety

Dimension runs project checks on your machine and can change files in the selected project. Git rollback uses a hard reset to the last green checkpoint. Use a dedicated worktree or commit your own work before starting. Review changes and checkpoints before sharing them.
