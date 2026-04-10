# Archer

Archer is an agentic code review tool for LLVM PRs, designed to deliver **precise, evidence-backed** reviews that minimize developers’ time spent reading, validating, and triaging comments.
It currently focuses on patches related to middle-end optimizations and reports only issues that come with **a reproducible proof of concept**. Archer is fully self-contained and can be paired with any LLM.

## Design

The key idea of Archer is to help the agent **think like an expert** when reviewing compiler code.
To achieve this, Archer combines *subsystem knowledge* with a *compiler-specific toolkit*.
Subsystem knowledge summarizes review experience from historical bug reports and fixes, while the compiler-specific toolkit provides the agent with tools for interacting with the compiler and validating its findings.

## Workflow

Given a PR, Archer performs review in four steps:

1. **Pass identification and knowledge loading.**
   Archer first identifies the optimization pass relevant to the patch and loads the corresponding pass knowledge.

2. **Analysis.**
   Archer recovers the relevant code context, inspects the patch semantics, and forms semantic suspicions about potential correctness issues.

3. **Validation.**
   Archer turns these suspicions into concrete evidence by invoking validation tools and checking whether the suspected issue can be reproduced.

4. **Structured reporting.**
   Archer produces a structured review containing both detailed bug analysis and a verified proof of concept.

## Environment Setup

Archer requires LLVM, Alive2, llubi, and Python on Linux.

### 1) Configure the environment

Copy the example file and fill in your model service configuration:

```bash
cp environments.example environments
```

Set the dependency installation directory:

```bash
export LLVM_AUTOREVIEW_DEPS_DIR=$HOME/archer-deps
```

### 2) Install dependencies

From the project root, run:

```bash
bash scripts/install.sh
```

This script installs and builds the required dependencies, including LLVM, Alive2, llubi, ccache, and the Python environment.

### 3) Activate the environment

In each new terminal, run:

```bash
source scripts/upenv.sh
```

This loads Archer’s environment variables, activates the virtual environment, and installs or updates Python dependencies.

### 4) Optional development setup

For local development, install:

```bash
pip install -r requirements.dev.txt
pre-commit install
```

## Usage

Run Archer with:

```bash
python main.py --pr <PR_ID> --model <MODEL_NAME> [options]
```

### Arguments

- `--pr`: LLVM Pull Request ID to review
- `--model`: LLM model name
- `--driver`: API driver (`openai`, `anthropic`, or `openai-generic`)
- `--stats`: Path to save generation statistics
- `--history`: Path to save chat history
- `--debug`: Enable verbose output

### Example

```bash
python main.py --pr 12345 --model gpt-4 --stats stats.json --debug
```
