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
   # Phase 2: Generate Test Cases
"""