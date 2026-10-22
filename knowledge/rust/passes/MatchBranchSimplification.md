# MatchBranchSimplification
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not treat structural similarity alone as sufficient; constant values and exhaustiveness must also be checked.
- The pass copies identical/equal statements unchanged and only substitutes the discriminant operand or an `IntToInt` cast for constant-assignment statements.
- The transformation introduces a temporary, StorageLive/move/StorageDead sequence, and patches the terminator; preserve def-use and storage scoping for valid MIR.
- Do not infer the result from old test names or comments; inspect the actual assignment lines and terminator.
- Do not rewrite `match EnumAu8 { A => 1, B => 3 }` where B has discriminant 2; the original returns 3, while a discriminant cast returns 2.
- Do not accept source-size bit equality as proof of target-size cast equality: the old logic used `l.to_bits_unchecked() == ScalarInt::try_from_uint(r, size).unwrap().to_bits_unchecked()` with an `is_signed` flag and could accept `-1i8 => 255i16`, which is wrong under sign extension.
- Do not conflate `SameByEq` constant equality with `CompareType::Discr` cast compatibility; only the latter may justify replacing the switch with a cast.
- A negative discriminant may appear as a large unsigned bit pattern; compare it according to the source type's signedness and then apply the target-size cast semantics.
- Do not assume a match on an integer is exhaustive merely because it has multiple explicit arms.
- Do not drop `match i { 1 => 1, 2 => 2, _ => 3 }`; input 0 would return 0 under a cast instead of 3.
- An unreachable otherwise block does not justify the fold by itself; the historical unsoundness was addressed by disabling the whole SimplifyToExp path, not merely by preserving exhaustive cases.
- `i8 -1 -> i16` is `-1` (0xFFFF), not `255` (0x00FF).
- `i8 -> u16` sign-extends then reinterprets: `-1i8 -> 65535`, `-128i8 -> 65408`; it is not zero extension.
- `u8 255 -> i16` is `255`, while `u8 255 -> u16` is also `255`.
- Truncation matters: `i16 -127 -> i8` is `-127` (0x81), so an arm returning `127i8` must block the fold; `u16 65535 -> u8` is `255`; `u16 65535 -> i8` is `-1`.
- Same-width `i128 -> u128` preserves the discriminant bit pattern, so an exhaustive `i128` enum may fold to `discr as u128`.
- Do not use a simple `is_signed` flag to decide compatibility; it can mix zero and sign extension, the historical error described as a mix of zext and sext.
- Do not assume that a previously accepted fold in MIR tests was correct; the old tests accepted many signed/unsigned width combinations despite the unsoundness.
- Do not remove the `unsound_mir_opts` gate without also fixing the constant comparison; doing so would re-expose the miscompile.
- Do not treat `otherwise: unreachable` as sufficient to re-enable the fold; the historical disablement covered the whole path.
- Do not copy obsolete assertion intent from comments such as `// CHECH: return`; check whether the corrected test expects `// CHECK: switchInt`.
- The cast patterns to watch for include `_3 as u128`, `_3 as i8`, `_3 as i16`, `_3 as u16`, and `_3 as u8` from discriminant types such as `isize`, `i128`, `i16`, `i8`, or `u8`.
- Do not infer pass behavior from a retained test name, old comment, or old assertion intent; inspect the actual assignment and terminator lines.
- A test with `// CHECK-NOT: switchInt` alone is insufficient for a negative case; use `// CHECK: switchInt` when the switch must remain.
- Do not use tests to claim universal equivalence; they only exercise concrete MIR inputs and concrete discriminant values.
- Do not overlook structural non-triggers such as unequal arm statement counts, duplicate assignments, or different terminators.

## Patterns Not Well Handled

### Recognize a foldable integer-discriminant SwitchInt into an IntToInt cast
MatchBranchSimplification can replace a `switchInt` over an integer/enum discriminant with a single `_0 = <discriminant> as RetTy (IntToInt)` assignment when the switch is an exhaustive constant mapping. The structural trigger is a 2..=64-target `SwitchInt` whose discriminant is an operand, all targets distinct, the `otherwise` block empty-unreachable, all target blocks ending in the same terminator, equal statement counts in the compared target blocks, and aligned constant assignments to the same place. The discriminant and arm-constant types may differ, in which case the emitted assignment uses an `IntToInt` cast.
Preconditions: The terminator is `SwitchInt` over `Operand::Copy`/`Operand::Move` and the explicit target count is >= 2 and <= 64.; All switch targets, including the otherwise target, are distinct: `targets.is_distinct()`.; The otherwise target is empty-unreachable: `bbs[targets.otherwise()].is_empty_unreachable()`.; All explicit target blocks have the same terminator kind, and the first two targets have equal statement counts with one-to-one aligned statements.; Aligned statements are either identical or integral constant assignments to the same place; the constant must be validated against the discriminant value selecting that arm.; The rewrite is only applied at `mir_opt_level() >= 1`.; When the discriminant and arm-constant types differ, the emitted `Rvalue::Cast(CastKind::IntToInt, ...)` must be semantically equal to the arm constants.
Pitfalls: Do not treat structural similarity alone as sufficient; constant values and exhaustiveness must also be checked.; The pass copies identical/equal statements unchanged and only substitutes the discriminant operand or an `IntToInt` cast for constant-assignment statements.; The transformation introduces a temporary, StorageLive/move/StorageDead sequence, and patches the terminator; preserve def-use and storage scoping for valid MIR.; Do not infer the result from old test names or comments; inspect the actual assignment lines and terminator.
Test strategy: Use MIR-dump tests whose positive cases assert `// CHECK-NOT: switchInt` and an assignment such as `// CHECK: _0 = _3 as i16 (IntToInt);`. Add custom-MIR variants with different instruction lengths and duplicate assignments, and assert the switch remains when the structural pattern does not align. These are focused differential observations, not universal proof of equivalence.
Cases: 120614-f4407370dbb67115bc4acc97dbbdceba0f6d17f3
Source: https://github.com/rust-lang/rust/pull/120614
> Transforms match into an assignment statement
> if targets.iter().len() < 2 || targets.iter().len() > 64 {
> if !targets.is_distinct() {
> if !bbs[targets.otherwise()].is_empty_unreachable() {
> // CHECK: _0 = _3 as i16 (IntToInt);

### Require each arm constant to equal the actual IntToInt result of its discriminant
A historical SimplifyToExp rewrite could collapse a constant-arm match on an integer discriminant purely from the shape of the switch. The required invariant is stronger: for every reachable case value, the arm's constant must equal what `IntToInt` produces at the target type. A transform that emits `discr as T` when an arm returns a different value is incorrect. For example, an enum variant with discriminant 2 whose arm returns 3 cannot be folded, and `-1i8` cannot justify an arm returning `255i16` because the cast sign-extends to `-1i16`.
Preconditions: Every arm constant-to-discriminant mapping is checked, not merely the first arm or the syntactic presence of constants.; The comparison is between the actual target-size cast result and the arm's target `ScalarInt`, rather than source-size bit-pattern equality.; The first/second arm check and every remaining target all satisfy the cast-equality requirement before the switch is replaced.; Signed and negative discriminants are handled with explicit signed interpretation and cast semantics at the target size.
Pitfalls: Do not rewrite `match EnumAu8 { A => 1, B => 3 }` where B has discriminant 2; the original returns 3, while a discriminant cast returns 2.; Do not accept source-size bit equality as proof of target-size cast equality: the old logic used `l.to_bits_unchecked() == ScalarInt::try_from_uint(r, size).unwrap().to_bits_unchecked()` with an `is_signed` flag and could accept `-1i8 => 255i16`, which is wrong under sign extension.; Do not conflate `SameByEq` constant equality with `CompareType::Discr` cast compatibility; only the latter may justify replacing the switch with a cast.; A negative discriminant may appear as a large unsigned bit pattern; compare it according to the source type's signedness and then apply the target-size cast semantics.
Test strategy: Pair programs that differ only in whether an arm constant equals the cast result, and inspect the MatchBranchSimplification MIR dump. Positive cases should show no `switchInt` and the `IntToInt` assignment; `*_failed` cases should retain `switchInt`. Include signed negative cases and deliberately wrong sext/zext/trunc constants. These tests pin the mapping invariant but do not by themselves prove general equivalence.
Cases: 120614-f4407370dbb67115bc4acc97dbbdceba0f6d17f3, 127324-1f9d9603c05a1fb56825b4fc54ea28aa04485024, 124156-b52be28fda8830a5d300deaa11da54d9a2c58d10
Source: https://github.com/rust-lang/rust/pull/120614
Source: https://github.com/rust-lang/rust/pull/127324
Source: https://github.com/rust-lang/rust/pull/124156
> The condition in #120614 is wrong, e.g. `-1i8` cannot be converted to `255i16`.
> The new approach is to check **if the case value after the `IntToInt` conversion equals the target value**.
> cast_scalar == target_scalar
> EnumAi8::_1_0xff => 255, // failed
> fn match_u8_i16_failed(i: EnumAu8) -> i16 {
> EnumAu8::B => 3,

### Do not collapse a reachable fallback or unmatched switch arm
The discriminant-cast rewrite is only valid when the switch is exhaustive for the reachable values, which in this pass is expressed by an empty-unreachable otherwise block. A reachable wildcard/default arm means the per-arm constant mapping is incomplete; replacing the switch with a cast would silently drop the fallback behavior. Historical `_fallback` regression cases retain `switchInt` for exactly this reason.
Preconditions: The otherwise block must be empty-unreachable before the fold is considered.; A reachable default/wildcard arm is a hard non-trigger even when all explicit arms assign constants that look cast-compatible.; An `otherwise: unreachable` arm alone is not sufficient unless the remaining constant-mapping and cast-equality checks also hold.
Pitfalls: Do not assume a match on an integer is exhaustive merely because it has multiple explicit arms.; Do not drop `match i { 1 => 1, 2 => 2, _ => 3 }`; input 0 would return 0 under a cast instead of 3.; An unreachable otherwise block does not justify the fold by itself; the historical unsoundness was addressed by disabling the whole SimplifyToExp path, not merely by preserving exhaustive cases.
Test strategy: Add paired positive and fallback cases; the fallback case should assert `// CHECK: switchInt` after the MatchBranchSimplification dump. Keep the otherwise block reachable in the negative program and compare observable results for an input that takes the fallback. This is a focused check of the exhaustiveness guard, not a general correctness proof.
Cases: 120614-f4407370dbb67115bc4acc97dbbdceba0f6d17f3, 127324-1f9d9603c05a1fb56825b4fc54ea28aa04485024, 124156-b52be28fda8830a5d300deaa11da54d9a2c58d10
Source: https://github.com/rust-lang/rust/pull/120614
Source: https://github.com/rust-lang/rust/pull/127324
Source: https://github.com/rust-lang/rust/pull/124156
> if !bbs[targets.otherwise()].is_empty_unreachable() {
> fn match_u8_i16_fallback(i: u8) -> i16 {
> switchInt(move _2) -> [1: bb3, 2: bb4, 3: bb5, 340282366920938463463374607431768211455: bb2, otherwise: bb1];
> // CHECK: switchInt

### Model IntToInt precisely: sign extension, zero extension, truncation, and same-width bit preservation
The validity of the fold depends on the target-size result of an integer-to-integer cast, not on flags or source-size bit patterns. For integer discriminants, `i8 -> i16/u16` sign-extends, `u8 -> i16/u16` zero-extends, `i16/u16 -> i8/u8` truncates, and same-width conversions such as `i128 -> u128` preserve the bit pattern. The corrected implementation computes the real cast result and requires equality with the arm constant before enabling the rewrite.
Preconditions: The discriminant type is `Uint` or `Int`, and arm constants are integer scalars.; For a source `Uint`, obtain the unsigned interpretation; for a source `Int`, obtain the signed interpretation and represent it as `u128` for conversion.; Truncate the value to the target type's size to form the candidate `ScalarInt`, then compare it with the target constant.; The transform must only proceed when this computed cast equality holds for all arms and the other structural/exhaustiveness conditions hold.
Pitfalls: `i8 -1 -> i16` is `-1` (0xFFFF), not `255` (0x00FF).; `i8 -> u16` sign-extends then reinterprets: `-1i8 -> 65535`, `-128i8 -> 65408`; it is not zero extension.; `u8 255 -> i16` is `255`, while `u8 255 -> u16` is also `255`.; Truncation matters: `i16 -127 -> i8` is `-127` (0x81), so an arm returning `127i8` must block the fold; `u16 65535 -> u8` is `255`; `u16 65535 -> i8` is `-1`.; Same-width `i128 -> u128` preserves the discriminant bit pattern, so an exhaustive `i128` enum may fold to `discr as u128`.; Do not use a simple `is_signed` flag to decide compatibility; it can mix zero and sign extension, the historical error described as a mix of zext and sext.
Test strategy: Construct MIR-opt cases for each cast bucket: no-op, sign extension, zero extension, truncation, and same-width `i128 -> u128`. Use explicit variant names encoding source/target signedness and values, with positive cases asserting `// CHECK-NOT: switchInt` and `// CHECK: IntToInt`, and paired failed cases with one wrong sext/zext/trunc constant asserting `// CHECK: switchInt`. These are representative cast checks rather than exhaustive proof.
Cases: 127324-1f9d9603c05a1fb56825b4fc54ea28aa04485024, 124156-b52be28fda8830a5d300deaa11da54d9a2c58d10, 120614-f4407370dbb67115bc4acc97dbbdceba0f6d17f3
Source: https://github.com/rust-lang/rust/pull/127324
Source: https://github.com/rust-lang/rust/pull/124156
Source: https://github.com/rust-lang/rust/pull/120614
> - `i8` to `i16`/`u16`: sign extension.
> - `u8` to `i16`/`u16`: zero extension.
> - `i16`/`u16` to `i8`/`u8`: truncate to the target size.
> The previous error was a mix of zext and sext.
> // Converting `-1i8` to `255u16` is zext.
> let v = size.truncate(v);
> /// Check if the cast constant using `IntToInt` is equal to the target constant.

### Historical disablement of SimplifyToExp and the gate/regression expectation
A historical MatchBranchSimplification version emitted `_3 = move _2; _0 = _3 as T (IntToInt);` in place of a constant-arm discriminant switch, and that rewrite was reported unsound. The historical fix disabled this `SimplifyToExp` path behind `unsound_mir_opts`, changing regression expectations from expecting a cast to expecting the original `switchInt`. Later work restored the optimization only after replacing the faulty comparison with actual cast-result equality. When analyzing historical behavior, distinguish the default disabled state from the gated experimental state.
Preconditions: Historical pre-fix behavior may show the fold, but the default corrected behavior keeps `switchInt` and its constant-arm blocks.; The disabled path is gated by `tcx.sess.opts.unstable_opts.unsound_mir_opts` in the historical version.; The later restoration requires `can_cast`-style equality between the computed `IntToInt` result and the target constant, then removes the gate.; Regression expectations must be based on the actual terminator and assignments in each dump, not on retained test names or stale comments.
Pitfalls: Do not assume that a previously accepted fold in MIR tests was correct; the old tests accepted many signed/unsigned width combinations despite the unsoundness.; Do not remove the `unsound_mir_opts` gate without also fixing the constant comparison; doing so would re-expose the miscompile.; Do not treat `otherwise: unreachable` as sufficient to re-enable the fold; the historical disablement covered the whole path.; Do not copy obsolete assertion intent from comments such as `// CHECH: return`; check whether the corrected test expects `// CHECK: switchInt`.; The cast patterns to watch for include `_3 as u128`, `_3 as i8`, `_3 as i16`, `_3 as u16`, and `_3 as u8` from discriminant types such as `isize`, `i128`, `i16`, `i8`, or `u8`.
Test strategy: Use differential MIR scenarios: one revision keeps the constant-arm `switchInt`, the other applies the discriminant-cast fold. Assert `// CHECK: switchInt` for the corrected/default historical behavior and `// CHECK-NOT: switchInt` plus the `IntToInt` assignment only for the enabled positive case. Cover `i128 -> u128`, `i16 -> i8`, `i8 -> i16`, `u8 -> i16`, `u8 -> u16`, and `isize -> u8/i8`. Such tests compare specific MIR shapes and are not proof that every possible input is equivalent.
Cases: 124156-b52be28fda8830a5d300deaa11da54d9a2c58d10, 127324-1f9d9603c05a1fb56825b4fc54ea28aa04485024, 120614-f4407370dbb67115bc4acc97dbbdceba0f6d17f3
Source: https://github.com/rust-lang/rust/pull/124156
Source: https://github.com/rust-lang/rust/pull/127324
Source: https://github.com/rust-lang/rust/pull/120614
> Due to the miscompilation mentioned in #124150, We need to disable MatchBranchSimplification temporarily.
> // unsound: https://github.com/rust-lang/rust/issues/124150
> StorageLive(_3);
> _3 = move _2;
> _0 = _3 as u128 (IntToInt);
> // CHECK-NOT: switchInt
> // CHECK: switchInt
> 3. Gradually add back the removed transforms (possibly multiple PRs).

### Focused MIR testing for fold versus no-fold cases
MatchBranchSimplification behavior should be validated with paired MIR tests that vary only the condition under test: matching versus mismatching constants, exhaustive versus reachable fallback, correct versus incorrect cast semantics, and aligned versus differently sized arm blocks. The useful observations are the presence or absence of `switchInt` and the shape of the resulting `IntToInt` assignment, not assumptions based on test names or comments.
Preconditions: Each test is emitted with the pass-specific MIR dump and uses pass-specific unit-test annotations.; Positive cases assert no `switchInt` and the expected cast assignment; negative cases assert `switchInt` remains.; Differential pairs keep the source shape as similar as possible and vary only the constant, fallback reachability, signedness/width, or statement alignment.; Tests cover explicit discriminator values and boundaries, including negative values and wide values, as well as multi-statement arms and custom-MIR length variations.
Pitfalls: Do not infer pass behavior from a retained test name, old comment, or old assertion intent; inspect the actual assignment and terminator lines.; A test with `// CHECK-NOT: switchInt` alone is insufficient for a negative case; use `// CHECK: switchInt` when the switch must remain.; Do not use tests to claim universal equivalence; they only exercise concrete MIR inputs and concrete discriminant values.; Do not overlook structural non-triggers such as unequal arm statement counts, duplicate assignments, or different terminators.
Test strategy: Run `//@ unit-test: MatchBranchSimplification` with `// EMIT_MIR <fn>.MatchBranchSimplification.diff`. For positives expect `// CHECK-NOT: switchInt` and `// CHECK: _0 = _3 as i16 (IntToInt);` or `// CHECK: IntToInt`; for negatives expect `// CHECK: switchInt`. Include `_failed`, `_fallback`, `_failed_len_*`, and custom-MIR `_2` variants. Cover `u8/i8/u16/i16/i128/u128` combinations, explicit values such as 65535, 65533, and `u128::MAX`, and negative variants such as `-1`, `-127`, `-128`. These focused pairs expose the historical error directions without claiming exhaustive proof.
Cases: 120614-f4407370dbb67115bc4acc97dbbdceba0f6d17f3, 124156-b52be28fda8830a5d300deaa11da54d9a2c58d10, 127324-1f9d9603c05a1fb56825b4fc54ea28aa04485024
Source: https://github.com/rust-lang/rust/pull/120614
Source: https://github.com/rust-lang/rust/pull/124156
Source: https://github.com/rust-lang/rust/pull/127324
> // CHECK-NOT: switchInt
> // CHECK: switchInt
> // CHECK: IntToInt
> // CHECK: _0 = _3 as i16 (IntToInt);
> // CHECH: return
> EnumAu16::u65535_0xffff => 127, // failed
> EnumAi16::o127_0xff7f => -127, // failed
