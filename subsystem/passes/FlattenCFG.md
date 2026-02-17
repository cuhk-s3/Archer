# Issue 70900

## Incorrect Handling of PHI Nodes in If-Region Merging

**Description**:
The bug is triggered when the `FlattenCFG` pass attempts to merge two adjacent conditional regions (if-regions) where the entry block of the second region (which acts as the merge point of the first) contains a PHI node. The optimization aims to simplify control flow by combining the conditions of the two regions. However, the presence of a PHI node in the shared block implies that the program state depends on the specific path taken through the first region. The transformation logic fails to correctly preserve this path-dependent value when restructuring the control flow edges and conditions. Consequently, the merged code may use incorrect values for variables defined by the PHI node, leading to functional correctness issues.

## Example

### Original IR
```llvm
define i32 @test_phi_merge(i1 %c1, i1 %c2, i32 %v1, i32 %v2) {
entry:
  br i1 %c1, label %if.then, label %merge

if.then:
  br label %merge

merge:
  ; This PHI node makes the value path-dependent on the first region
  %phi = phi i32 [ %v1, %entry ], [ %v2, %if.then ]
  br i1 %c2, label %use, label %exit

use:
  ; Usage of the path-dependent value
  %res = add i32 %phi, 1
  br label %exit

exit:
  %ret = phi i32 [ 0, %merge ], [ %res, %use ]
  ret i32 %ret
}
```
### Optimized IR
```llvm
define i32 @test_phi_merge(i1 %c1, i1 %c2, i32 %v1, i32 %v2) {
entry:
  ; BUG: The optimization merged the regions but failed to preserve the PHI logic.
  ; It incorrectly removed the check for %c1 and assumes %v1 is always the value.
  br i1 %c2, label %use, label %exit

use:
  ; Incorrectly uses %v1 directly, ignoring that %v2 should be used if %c1 was true
  %res = add i32 %v1, 1
  br label %exit

exit:
  %ret = phi i32 [ 0, %entry ], [ %res, %use ]
  ret i32 %ret
}
```
