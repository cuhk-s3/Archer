# Archer

Archer is an automated agent designed to review optimization-related patches. It leverages Code Agent to analyze code, generate test strategies, and perform verification using tools like Alive2 and differential testing.

## Usage

Run the agent using `main.py` with the required arguments:

```bash
python main.py --issue <ISSUE_ID> --model <MODEL_NAME> [options]
```

### Arguments

- `--issue`: (Required) The ID of the LLVM issue to review.
- `--model`: (Required) The LLM model to use (e.g., `gpt-4`).
- `--driver`: The LLM API driver to use. Choices: `openai` (default), `anthropic`, `openai-generic`.
- `--stats`: Path to save generation statistics as a JSON file.
- `--history`: Path to save the chat history as a JSON file.
- `--debug`: Enable verbose debug output.

### Example

```bash
python main.py --issue 12345 --model gpt-4 --stats stats.json --debug
```

## Structure

- **Phase 1 (Analysis)**: The agent analyzes the fix and proposes potential test strategies.
- **Phase 2 (Verification)**: The agent generates test cases, runs verification tools (`verify`, `difftest`), and reports found bugs.
