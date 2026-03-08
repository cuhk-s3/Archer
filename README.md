# Archer

Archer is an automated agent designed to review optimization-related patches. It leverages Code Agent to analyze code, generate test strategies, and perform verification using tools like Alive2 and differential testing.

## Environment Setup

Archer depends on LLVM/Alive2/llubi and a Python runtime. Using bash or zsh on Linux is recommended.

### 1) System Prerequisites

Install the following tools first (exact versions are not strictly required, but newer versions are recommended):

- `git`
- `cmake`
- `ninja`
- `gdb`
- `wget`
- `unzip`
- `python3` (and make sure `python3 -m venv` is available)

### 2) Configure Environment Variables

1. Copy the example environment file:

```bash
cp environments.example environments
```

2. Fill in your model service configuration in `environments`:

- `LLVM_AUTOREVIEW_LM_API_ENDPOINT`
- `LLVM_AUTOREVIEW_LM_API_KEY`

3. Set the dependency installation directory (adjust the path as needed):

```bash
export LLVM_AUTOREVIEW_DEPS_DIR=$HOME/archer-deps
```

### 3) Install LLVM and Related Dependencies (First Time Only)

Run this in the project root:

```bash
bash scripts/install.sh
```

This script automatically downloads and builds LLVM, Alive2, llubi, and ccache, and creates a Python virtual environment. Some steps require `sudo`.

### 4) Activate the Project Environment (Run in Every New Terminal)

```bash
source scripts/upenv.sh
```

This step will:

- Export environment variables required by Archer
- Activate the virtual environment
- Automatically install/update Python dependencies from `requirements.txt`

### 5) (Optional) Development Dependencies

If you need local development/linting tools, also install:

```bash
pip install -r requirements.dev.txt
```

Then install pre-commit hooks:

```bash
pre-commit install
```

Optional: run all checks once on the current repository:

```bash
pre-commit run --all-files
```

## Usage

Run the agent using `main.py` with the required arguments:

```bash
python main.py --pr <PR_ID> --model <MODEL_NAME> [options]
```

### Arguments

- `--pr`: (Required) The ID of the LLVM Pull Request to review.
- `--model`: (Required) The LLM model to use (e.g., `gpt-4`).
- `--driver`: The LLM API driver to use. Choices: `openai` (default), `anthropic`, `openai-generic`.
- `--stats`: Path to save generation statistics as a JSON file.
- `--history`: Path to save the chat history as a JSON file.
- `--debug`: Enable verbose debug output.

### Example

```bash
python main.py --pr 12345 --model gpt-4 --stats stats.json --debug
```

## Structure

- **Phase 1 (Analysis)**: The agent analyzes the fix and proposes potential test strategies.
- **Phase 2 (Verification)**: The agent generates test cases, runs verification tools (`verify`, `difftest`), and reports found bugs.
