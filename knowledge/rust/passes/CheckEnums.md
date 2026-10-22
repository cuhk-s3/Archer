# CheckEnums
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Signed-to-u128 casting sign-extends negative discriminants; using that value directly as the switch scrutinee compares the wrong bit pattern.
- Normalization must use the actual discriminant size, `discr.size.unsigned_int_max()`, rather than assuming a 128-bit width.
- Masking only the scrutinee is insufficient: switch target constants must also be truncated with `discr.size.truncate(discr_val)`.
- The invalid-construction assertion should report the normalized `discr_masked` value; otherwise branching can be correct while the diagnostic still reports an incorrect large value.
- Positive-discriminant cases do not exercise sign extension; the failure specifically appeared for negative values, including the all-ones u128 report.
- Finite paired tests and specified boundary inputs provide concrete evidence but do not by themselves prove universal equivalence for all enum layouts or discriminant values.

## Patterns Not Well Handled

### Normalize direct enum discriminants to the enum discriminant width before switch and invalid-value reporting
For CheckEnums' direct enum-construction check, a discriminant obtained through a cast must be reduced to the enum's discriminant width before it is used as the `SwitchInt` scrutinee, before target constants are formed, and before an invalid value is reported. Historical evidence states: "The discriminant check was not working correctly for negative numbers. This change fixes that by masking out the relevant bits correctly." The pre-fix check forwarded a sign-extended u128 from `insert_discr_cast_to_u128` into `SwitchInt` and into `AssertKind::InvalidEnumConstruction`; for a negative narrow discriminant, sign extension produced "trying to construct an enum from an invalid value 0xffffffffffffffffffffffffffffffff" instead of the narrow bit pattern. The corrected transformation introduces "// Mask out the bits of the discriminant type." with "let mask = discr.size.unsigned_int_max();", masks the scrutinee using `BinOp::BitAnd`, truncates each target via `.map(|discr_val| (discr.size.truncate(discr_val), new_block))`, and reports the normalized operand via "msg: Box::new(AssertKind::InvalidEnumConstruction(Operand::Copy(discr_masked)))". Thus valid negative discriminants are accepted and invalid values are reported at the enum's discriminant width.
Preconditions: The `insert_direct_enum_check` path is active for MIR enum-construction checks, exercised with debug assertions enabled.; The enum has explicit discriminants, including negative values, and may use a narrow representation or `#[repr(i64)]`.; An unsafe operation such as `std::mem::transmute` supplies or attempts to supply an underlying discriminant bit pattern, causing the generated enum-construction check to run.; The source discriminant has been cast to u128, so signed values may be sign-extended and must be normalized using the enum's discriminant size.
Pitfalls: Signed-to-u128 casting sign-extends negative discriminants; using that value directly as the switch scrutinee compares the wrong bit pattern.; Normalization must use the actual discriminant size, `discr.size.unsigned_int_max()`, rather than assuming a 128-bit width.; Masking only the scrutinee is insufficient: switch target constants must also be truncated with `discr.size.truncate(discr_val)`.; The invalid-construction assertion should report the normalized `discr_masked` value; otherwise branching can be correct while the diagnostic still reports an incorrect large value.; Positive-discriminant cases do not exercise sign extension; the failure specifically appeared for negative values, including the all-ones u128 report.; Finite paired tests and specified boundary inputs provide concrete evidence but do not by themselves prove universal equivalence for all enum layouts or discriminant values.
Test strategy: Use paired Rust UI tests with debug assertions. For acceptance, cover enums with negative and positive discriminants, including narrow representations and `#[repr(i64)]` boundaries such as `i64::MIN` and `i64::MAX`; transmute each valid underlying integer into the enum and assert that it equals the expected variant. For rejection, use an enum with `A = -2, B = -1, C = 1`, transmute an invalid `i8` such as `-3`, and run a `run-fail` test with "//@ error-pattern: trying to construct an enum from an invalid value 0xfd" to verify masking to the i8 width. Include the concrete input sequence `-3i8, -2i8, -1i8, 0i8, 1i8, 2i8` to distinguish sign-extended behavior from width-normalized behavior.
Cases: 143273-8a0d8dde44b3b413488aa69caebc9cc3fb0f7edf
Source: https://github.com/rust-lang/rust/pull/143273
> Make the enum check work for negative discriminants
> The discriminant check was not working correctly for negative numbers. This change fixes that by masking out the relevant bits correctly.
> New enum discrimintant check doesn't work for negative numbers
> trying to construct an enum from an invalid value 0xffffffffffffffffffffffffffffffff
> // Mask out the bits of the discriminant type.
> let mask = discr.size.unsigned_int_max();
> .map(|discr_val| (discr.size.truncate(discr_val), new_block)),
> msg: Box::new(AssertKind::InvalidEnumConstruction(Operand::Copy(discr_masked))),
> //@ error-pattern: trying to construct an enum from an invalid value 0xfd
> let val: Bar = unsafe { std::mem::transmute::<i64, Bar>(i64::MIN) };
