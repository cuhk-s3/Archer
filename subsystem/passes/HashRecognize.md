# Issue 165382

## Incorrect Handling of Live-Out Values in CRC Loop Recognition

**Description**:
The bug is triggered when the compiler's `HashRecognize` pass identifies a loop as implementing a CRC (Cyclic Redundancy Check) algorithm. This pattern typically involves two recurrences: a "conditional recurrence" that accumulates the CRC value and a "simple recurrence" (often a bitwise shift) that evolves the input data.

The optimization logic assumes that the simple recurrence is purely auxiliary and exists solely to drive the CRC calculation. Consequently, it attempts to replace the loop with an optimized CRC intrinsic, discarding the original instruction sequence. The flaw is that the optimizer fails to check if the instruction computing the simple recurrence has users outside the loop (i.e., if the value is live-out). If the evolved data value is used after the loop, the transformation incorrectly removes the necessary computation, causing the external code to use undefined or incorrect values.

## Example

### Original IR
```llvm
define i32 @crc_liveout_bug(i32 %crc, i32 %data, i32 %n) {
entry:
  %cmp = icmp eq i32 %n, 0
  br i1 %cmp, label %exit, label %loop

loop:
  %i = phi i32 [ 0, %entry ], [ %i.next, %loop ]
  %c = phi i32 [ %crc, %entry ], [ %c.next, %loop ]
  %d = phi i32 [ %data, %entry ], [ %d.next, %loop ]

  ; Simple recurrence: evolves the input data (live-out)
  %d.next = lshr i32 %d, 1

  ; Conditional recurrence: CRC calculation
  %c.shr = lshr i32 %c, 1
  %xor = xor i32 %c, %d
  %bit = and i32 %xor, 1
  %cond = icmp ne i32 %bit, 0
  %poly = select i1 %cond, i32 3988292384, i32 0
  %c.next = xor i32 %c.shr, %poly

  %i.next = add i32 %i, 1
  %exitcond = icmp eq i32 %i.next, %n
  br i1 %exitcond, label %exit, label %loop

exit:
  ; The bug is triggered because %d.next is used here
  %res = phi i32 [ %data, %entry ], [ %d.next, %loop ]
  ret i32 %res
}
```
### Optimized IR
```llvm
define i32 @crc_liveout_bug(i32 %crc, i32 %data, i32 %n) {
entry:
  %cmp = icmp eq i32 %n, 0
  br i1 %cmp, label %exit, label %loop_bypass

loop_bypass:
  ; The optimizer recognized the loop as a CRC idiom and replaced it.
  ; However, it failed to preserve the calculation for %d.next.
  ; (CRC intrinsic call or optimized sequence would be here)
  br label %exit

exit:
  ; The value corresponding to the loop path is now undef because
  ; the simple recurrence instruction was removed.
  %res = phi i32 [ %data, %entry ], [ undef, %loop_bypass ]
  ret i32 %res
}
```
