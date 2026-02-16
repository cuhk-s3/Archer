PROMPT_SYSTEM_ANALYZE = """\
You are an expert in LLVM IR and compiler optimizations. 

## Context ##
Users provided an LLVM optimization bug and maintainers proposed a patch to fix. \
Fixes in the same pass might share similar issues, such as elements frequently missed \
and high-level patterns that are not well handled. 

## Your Task ##
Your task is to analyze a compiler bug report and its patch.
Summarize the bug triggering strategy at the LLVM IR level. 

## You Will Receive ##
- The original bug report, including the bug description.
- The patch that is proposed to fix the bug, including the code region that \
was modified and the commit message describing the fix.
"""

PROMPT_ANALYZE = """\
There is a {bug_type} issue report in {component}: 

{issue}

The maintainers proposed the following patch to fix the issue:

{patch}

## Your Task ##
Summarize the bug triggering strategy at the LLVM IR level. 
Describe the strategy in natural language, focusing strictly on the incorrect transformation logic. 
Be general and abstract, focusing on the pattern of instructions or transformations that caused the issue. 
For example, instead of saying 'fadd instruction', consider if it applies to other floating point operations or binary operators. 
Do NOT reference specific commits, file names, or implementation details of the fix code. 

## Output Format ##
The output should be in Markdown format and follow this structure:

- **Summary Title**: A concise title summarizing the bug triggering strategy, which starts with a level-2 heading (##).
- **Description**: A detailed description of the bug triggering strategy.

Please do not include any implementation details of the fix, such as specific code changes, file names, or commit messages. 
Focus solely on the high-level pattern of instructions or transformations that led to the issue.
"""

PROMPT_SYSTEM_VERIFY = """\
You are an expert in LLVM IR and compiler optimizations. 

## Context ##
Users provides a bug-triggering strategy at the LLVM IR level, which is a high-level description of the pattern of instructions or transformations that can trigger a compiler bug. 
This strategy needs to be verified to ensure that it accurately captures the conditions that can lead to the bug.

## Your Task ##
Generate a minimal reproducible test case in LLVM IR that follows the provided bug-triggering strategy. 

## You Will Receive ##
- The bug-triggering strategy, which describes the pattern of instructions or transformations that can trigger the
"""

PROMPT_VERIFY = """\
Here is a bug-triggering strategy at the LLVM IR level:

{strategy}

## Your Task ##
Based on the provided bug-triggering strategy, generate a minimal reproducible test case in LLVM IR that follows the strategy. 
The test case should be as simple as possible while still triggering the bug, and it should be suitable for use in the LLVM test suite.
The test cases should be a pair of original LLVM IR code and optimized LLVM IR code, where the original code can trigger the bug and \
the optimized code is the result of applying the optimization pass that contains the bug.

## Output Format ##
Only output the LLVM IR code without any explanation. The output should be in JSON format and follow this structure:

```json
{{
  "original_ir": "The original LLVM IR code that can trigger the bug.",
  "optimized_ir": "The optimized LLVM IR code after applying the optimization pass, which should demonstrate the incorrect transformation."
}}
```
"""
