# Issue 80113

## Failure to Drop Poison-Generating Flags on Fully-Demanded Users

## Description
The bug is triggered in the Bit-Tracking Dead Code Elimination (BDCE) pass when the optimizer simplifies an instruction (e.g., replacing unused bits with zero) because its output bits are not fully demanded. To preserve correctness, the optimizer is supposed to clear poison-generating flags (such as `nsw`, `nuw`, or `exact`) from any instructions that use this simplified value, as the modified input might violate the assumptions implied by those flags.

The issue arises when a user of the simplified instruction demands all of its own output bits (i.e., the user's result is fully used). The optimization logic incorrectly assumes that because the user's output is fully demanded, the user instruction itself does not need to be visited or modified. Consequently, the optimizer skips clearing the poison-generating flags on this user. When the operand is subsequently simplified, the retained flags on the user instruction may no longer hold true for the new input value, causing the instruction to incorrectly produce a poison value (undefined behavior) instead of a valid result.

## Example

### Original IR
```llvm
define i32 @test(i32 %x) {
  ; %A has high bits set (e.g., 0xFFFFFF80 if %x is 0)
  %A = or i32 %x, -128
  ; shl nsw is valid because input is negative and result is negative (no sign change)
  %B = shl nsw i32 %A, 24
  ret i32 %B
}
```
### Optimized IR
```llvm
define i32 @test(i32 %x) {
  ; BDCE simplifies the constant because high bits are not demanded by the shl
  ; -128 (0xFFFFFF80) becomes 128 (0x00000080)
  %A = or i32 %x, 128
  ; BUG: nsw flag is retained. Input is now positive (128), result is negative (INT_MIN).
  ; This sign change violates nsw, causing poison.
  %B = shl nsw i32 %A, 24
  ret i32 %B
}
```
