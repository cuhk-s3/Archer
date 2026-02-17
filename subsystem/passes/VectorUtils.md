# Issue 47927

## Unsafe Bit-Width Reduction for Shift Operations

**Description**
The bug is triggered during the loop vectorization pass when the compiler attempts to optimize integer operations by reducing their bit width (e.g., demoting a 32-bit operation to 8 bits). This reduction is based on an analysis of "demanded bits," which determines that the upper bits of an instruction's result are unused, often because the result is subsequently truncated.

The issue arises because the compiler determines the target bit width based solely on the usage of the result, ignoring the constraints of the operands. This is specifically problematic for right-shift instructions. If the compiler shrinks a shift instruction to a width narrower than the constant shift amount, or narrower than the position of the significant bits in the input operand, the operation becomes semantically incorrect. For example, if a value is shifted right by a large constant (e.g., 18) but the operation is demoted to a smaller width (e.g., 8 bits), the input is implicitly truncated to 8 bits *before* the shift. Since the shift amount exceeds the new bit width, or the significant bits were in the upper part of the original value, the result becomes incorrect (typically zero). The optimization fails to verify that all operands, including constant shift amounts, can be safely represented and processed within the reduced bit width.

## Example

### Original IR
```llvm
define void @unsafe_shift_reduction(i32* %in, i8* %out, i32 %n) {
entry:
  %cond = icmp sgt i32 %n, 0
  br i1 %cond, label %loop, label %exit

loop:
  %iv = phi i32 [ 0, %entry ], [ %iv.next, %loop ]
  %gep.in = getelementptr inbounds i32, i32* %in, i32 %iv
  %val = load i32, i32* %gep.in, align 4
  ; The operation to be optimized: Right shift by 16
  %shr = lshr i32 %val, 16
  ; Truncation to 8 bits, which triggers the demanded bits analysis
  %trunc = trunc i32 %shr to i8
  %gep.out = getelementptr inbounds i8, i8* %out, i32 %iv
  store i8 %trunc, i8* %gep.out, align 1
  %iv.next = add i32 %iv, 1
  %exit.cond = icmp eq i32 %iv.next, %n
  br i1 %exit.cond, label %exit, label %loop

exit:
  ret void
}
```
### Optimized IR
```llvm
define void @unsafe_shift_reduction(i32* %in, i8* %out, i32 %n) {
entry:
  %min.iters.check = icmp ult i32 %n, 4
  br i1 %min.iters.check, label %scalar.ph, label %vector.ph

vector.ph:
  %n.vec = and i32 %n, -4
  br label %vector.body

vector.body:
  %index = phi i32 [ 0, %vector.ph ], [ %index.next, %vector.body ]
  %gep.in = getelementptr inbounds i32, i32* %in, i32 %index
  %vec.ptr = bitcast i32* %gep.in to <4 x i32>*
  %wide.load = load <4 x i32>, <4 x i32>* %vec.ptr, align 4
  
  ; BUG: The compiler incorrectly demoted the shift to 8 bits based on the destination type.
  ; It truncated the input operand to 8 bits BEFORE the shift.
  ; Since the shift amount is 16, shifting an 8-bit value by 16 is undefined behavior (poison),
  ; and logically incorrect as the upper bits of the original i32 are lost.
  %trunc.in = trunc <4 x i32> %wide.load to <4 x i8>
  %shr = lshr <4 x i8> %trunc.in, <i8 16, i8 16, i8 16, i8 16>
  
  %gep.out = getelementptr inbounds i8, i8* %out, i32 %index
  %vec.out = bitcast i8* %gep.out to <4 x i8>*
  store <4 x i8> %shr, <4 x i8>* %vec.out, align 1
  %index.next = add i32 %index, 4
  %done = icmp eq i32 %index.next, %n.vec
  br i1 %done, label %middle.block, label %vector.body

middle.block:
  %cmp.n = icmp eq i32 %n.vec, %n
  br i1 %cmp.n, label %exit, label %scalar.ph

scalar.ph:
  %bc.resume.val = phi i32 [ %n.vec, %middle.block ], [ 0, %entry ]
  br label %loop

loop:
  %iv = phi i32 [ %bc.resume.val, %scalar.ph ], [ %iv.next, %loop ]
  %gep.in.scalar = getelementptr inbounds i32, i32* %in, i32 %iv
  %val = load i32, i32* %gep.in.scalar, align 4
  %shr.scalar = lshr i32 %val, 16
  %trunc.scalar = trunc i32 %shr.scalar to i8
  %gep.out.scalar = getelementptr inbounds i8, i8* %out, i32 %iv
  store i8 %trunc.scalar, i8* %gep.out.scalar, align 1
  %iv.next = add i32 %iv, 1
  %exit.cond = icmp eq i32 %iv.next, %n
  br i1 %exit.cond, label %exit, label %loop

exit:
  ret void
}
```
