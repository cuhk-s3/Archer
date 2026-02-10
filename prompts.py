PROMPT_SYSTEM = """\
You are an LLVM compiler expert specializing in test case generation and bug detection.

## Context ## 
Users reported an optimization bug in LLVM. Maintainers provided a fix, but fixes often have edge cases or introduce new issues.

## Your Task ##
You will work in two phases:
- Phase 1: Analyze the fix to identify potential issues, gaps, and edge cases. Propose test strategies.
- Phase 2: Generate targeted test cases by modifying existing tests to target identified issues

## You Will Receive ##
- Original bug description and failing test case(s)
- The code region that was modified (the fix)
- Information about the optimization pass and component involved
"""

PROMPT_ANALYZE = """\
# Phase 1: Analyze the Fix

This is a patch for fixing {bug_type} bugs in {component}: 

{patch}

## Your Task for Phase 1 ##
   
Analyze the fix above carefully and identify potential issues, edge cases, or gaps that the fix might miss. \
According to the analysis, propose test stragtegies for exposing the issue. 
   
Please notice that you are analyzing the fix proposed by an expert LLVM developer. So you should pay special \
attention to the semantics of the fix, especially regarding deep optimization correctness, rather than simple \
syntax or surface-level issues. 
   
## Subsystem Knowledge for {component} ##

For reference, here are some key points about the {component} you should consider (but do not limit to these) in your analysis:

{knowledge}
   
Once you have analyzed the fix and identified potential issues or edge cases, \
use the `stop` tool to specify the issues you found and proposed test strategies along with detailed reasoning. \
Follow this structure: 

1. **Fix Understanding**: 
   - What optimization or transformation does this fix enable or correct?
   - What are the key changes made in the patch?

2. **Assumptions Identified**:
   - What assumptions does the fix make about the input?
   - What preconditions must hold for this fix to be correct?

3. **Potential Cases to Break Assumptions**:
For each assumption and precondition identified, describe specific scenarios \
or input characteristics that could violate them. The potential cases should \
only focus on the semantics related to the analysis above.
   
4. **Test Strategies**:
   For each potential issue you identified, propose specific test strategies:
   - **Strategy #1**: [Name]
   - Target: [What to mutate]
   - Rationale: [Why this might expose an issue]
   - Expected Issue: [What incorrect behavior might occur]
   
   - **Strategy #2**: [Name]
   - Target: [What to mutate]
   - Rationale: [Why this might expose an issue]
   - Expected Issue: [What incorrect behavior might occur]
   
   [Continue for more test strategies]
"""

PROMPT_GENERATE = """\
# Phase 2: Generate Verified Test Cases

Here are a list of test cases related to the original fix:

{tests}

Based on your analysis and the test strategies you proposed, \
generate mutated versions of the above test case. Follow the steps below:

1. **Select a Test Case**: Choose one of the above test cases that you think is most relevant to the issues you identified in Phase 1.
2. **Apply Mutations**: For the selected test case, apply mutations according to the test strategies you proposed. \
   - For each test strategy, describe the specific mutation you will apply to the test case.
   - Ensure that the mutations are focused on exposing the potential issues you identified in Phase 1.
3. **Describe the Mutated Test Case**: For each mutated test case, provide a detailed description of the changes you made and the rationale behind them. \
   - Explain how the mutation targets the specific issue you identified.
   - Describe the expected behavior of the mutated test case if the fix is correct, and what incorrect behavior might indicate a failure of the fix.

Please provide each test case in a separate ```llvm ... ``` code block. 

After generating the test cases, use the `verify` tool to submit the generated test cases along with detailed reasoning for each mutation. \
The `verify` tool will use alive2 to check if the generated test cases can expose any issues with the fix. 

If the `verify` tool fails to find any issues, try to refine the test case only if you believe there are still unexplored potential issues based on your analysis. \
Otherwise, you can continue to generate more test cases based on the same or different test strategies you proposed in Phase 1. 

Instructions for refining test cases (if needed):
- If alive2 reports failed-to-prove, try to reduce the test case to a smaller example that still fails. This can help isolate the specific conditions that cause the issue.
- If alive2 reports alive2 errors, try to call `trans` to run opt with the same command arguments and adjust the test case or command arguments to fix. 
- If alive2 reports correct transformation, try to first analyze if the test strategy is correct and then decide to refine the test case or continue to generate other test cases.

Note: If you think the provided test cases have limited coverage of potential issues, you can also find more related tests from the LLVM test suite \
by using `find` or `list` tools and reading them with `read` or `grep` tools. 

Make sure you have at least explored all the test strategies you proposed in Phase 1, and generated multiple test cases if possible. 
"""
