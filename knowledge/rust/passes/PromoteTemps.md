# PromoteTemps
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not fix only Div; Rem has the same signed-overflow hazard and needs the same rejection.
- Do not reject every division by -1: a non-minimum dividend such as 1 / -1 is still safe and promotable.
- Do not assume the divisor is literally written -1; constant-folded forms such as (0-1) must be recognized as -1.
- The check must be type-width-aware: -128i8 / -1 is the i8 minimum case just as i32::MIN / -1 is the i32 case.
- Preserve the zero-divisor precedence: 1/0, 1/(1-1), and (1+1)/(1-1) stay unpromotable because the divisor is zero, before any MIN/-1 reasoning applies.
- Use the integer interpretation for the signed test and the appropriate bit/integer evaluation for the zero test; the historical correction distinguished these operations.
- Do not expect both an overflow-panic lint and a duplicate constant-evaluation-failure diagnostic for the MIN / -1 and MIN % -1 lint cases; the historical regression removed the duplicate evaluation-failure expectations.
- Do not reject all const-fn promotion in const/static initializers; calls on the safe path are intentionally still promoted for backwards compatibility.
- Do not extend the allowance to inline consts; the historical condition explicitly excludes them.
- The safe path includes Call/Drop targets and Assert success targets because a callee that loops or panics already makes the whole const fail, but a branch such as SwitchInt stops the safe path.
- A call inside if/match must not be promoted merely because it is in a const/static initializer; dead code and conditional code are the key negative cases.
- Do not collect required_consts after promotion; the historical correction explicitly collects them before promotion so promoted consts remain accounted for in the outer body.
- Only unevaluated consts need to be added to required_consts, because only those can still fail to evaluate.
- When promotion creates a call-based promoted, set add_to_required and push the promoted operand into the parent's required_consts; otherwise a const moved into the promoted body can lose its failure.
- Fill the promoted body's own required_consts so standalone evaluation cannot silently miss a failure.
- After inlining, filter callee required_consts with is_required_const() before extending the caller because instantiate_and_normalize_erasing_regions may have evaluated some of them.
- After the enum gains a payload, matching only BorrowKind::Fake is too narrow; use BorrowKind::Fake(_) so both shallow and deep fake borrows are rejected.
- Do not treat deep fake borrows as ordinary promotable shared borrows merely because they look immutable or aliasable.
- A shallow fake borrow protects only the immediately borrowed place, not its projections; deref patterns need a deep fake borrow to reject guard mutation such as writing through the dereferenced box.
- Do not attribute fake-borrow erasure to promotion: cleanup must erase fake borrow assignments and fake reads, while promotion must refuse to promote them.

## Patterns Not Well Handled

### Integral Div/Rem promotion must exclude signed MIN / -1
Promotion may treat an integral BinOp::Div or BinOp::Rem as constant only when the operation cannot fail. A historical validator accepted any known nonzero constant divisor, which incorrectly promoted signed int::MIN / -1 and int::MIN % -1 even though those operations overflow and can panic. The corrected rule additionally requires, for signed types, that when the divisor is -1 (including a constant-folded -1) or unknown, the dividend be a known constant other than the signed type minimum; otherwise the operation is unpromotable. Zero or unknown divisors remain unpromotable through the separate nonzero check.
Preconditions: Promotion is validating an integral BinOp::Div or BinOp::Rem candidate whose operands are constants or can be constant-evaluated.; The type is signed and is one of i8, i16, i32, i64, i128, or isize.; The divisor is -1 directly or through constant folding, such as (0-1), and the dividend is the signed minimum for that type.; Under the historical logic, the divisor was merely checked as nonzero, so these fallible MIN / -1 cases passed promotion.
Pitfalls: Do not fix only Div; Rem has the same signed-overflow hazard and needs the same rejection.; Do not reject every division by -1: a non-minimum dividend such as 1 / -1 is still safe and promotable.; Do not assume the divisor is literally written -1; constant-folded forms such as (0-1) must be recognized as -1.; The check must be type-width-aware: -128i8 / -1 is the i8 minimum case just as i32::MIN / -1 is the i32 case.; Preserve the zero-divisor precedence: 1/0, 1/(1-1), and (1+1)/(1-1) stay unpromotable because the divisor is zero, before any MIN/-1 reasoning applies.; Use the integer interpretation for the signed test and the appropriate bit/integer evaluation for the zero test; the historical correction distinguished these operations.; Do not expect both an overflow-panic lint and a duplicate constant-evaluation-failure diagnostic for the MIN / -1 and MIN % -1 lint cases; the historical regression removed the duplicate evaluation-failure expectations.
Test strategy: Use focused promotion UI cases: borrowing &(i32::MIN/-1), &(i32::MIN/(0-1)), &(-128i8/-1), and analogous MIN % -1 expressions into a &'static reference must produce E0716 temporary-value-dropped-while-borrowed, proving they are not promoted. Verify safe boundaries still promote with static assertions such as &(1/1), &(0/1), &(1/-1), &(i32::MIN/1), and &(1%1). For lint coverage, check i8::MIN / -1 through isize::MIN / -1 and the corresponding remainder forms report the runtime-panic lint, and compare noopt, opt, and opt-with-overflow-checks stderr variants for consistent diagnostics. These are regression expectations, not a claim that finite tests prove general equivalence.
Cases: 121515-f32095cd8d43de470c2d3daa5b3cb8f494cfa770
Source: https://github.com/rust-lang/rust/pull/121515
> Subject: [PATCH] promotion: don't promote int::MIN / -1
> Looks like I entirely forgot about this case when adding the div-by-zero check, which was supposed to ensure that we never promote operations that can fail...
> // Integer division: the RHS must be a non-zero const.
> Some(x) if x != 0 => {}        // okay
> // Furthermore, for signed divison, we also have to exclude `int::MIN / -1`.
> Some(x) if x != lhs_min => {}  // okay
> let _val: &'static _ = &(i32::MIN/(0-1)); //~ ERROR temporary value dropped while borrowed
> // div-by-non-0 (and also not MIN/-1) is okay

### Const/static const-fn promotion only on the definitely executed safe path
For backwards compatibility, non-#[rustc_promotable] const fn calls in static and non-inline const initializers may be promoted even without the usual promotable attribute, but only when their basic block is guaranteed to execute. The historical rule allowed such calls anywhere in a const/static initializer, so a call placed in dead or conditional code could be promoted and then fail const evaluation even though it would never run. The corrected rule restricts promotion to blocks on the safe path from the start block, advancing through Goto, Call/Drop targets, and Assert success targets, and stopping at the first branch. Inline consts are excluded from this allowance, while #[rustc_promotable] callees remain permissible subject to validating their operands first.
Preconditions: The promotion context is Static or Const { inline: false }; inline consts do not receive the backwards-compatibility allowance.; The callee is a const fn but is not marked #[rustc_promotable].; The candidate call's basic block is not on the definitely executed safe path; in particular, it is inside a conditional or otherwise after a branch.; For #[rustc_promotable] callees, callee and argument operands must still be validated before the call is accepted.
Pitfalls: Do not reject all const-fn promotion in const/static initializers; calls on the safe path are intentionally still promoted for backwards compatibility.; Do not extend the allowance to inline consts; the historical condition explicitly excludes them.; The safe path includes Call/Drop targets and Assert success targets because a callee that loops or panics already makes the whole const fail, but a branch such as SwitchInt stops the safe path.; A call inside if/match must not be promoted merely because it is in a const/static initializer; dead code and conditional code are the key negative cases.
Test strategy: Use UI tests with a const fn that panics and a const fn returning false. In a const initializer, if the false-returning function guards a block that borrows &panic_const_fn(), expect E0716 temporary-dropped-while-borrowed, proving no promotion in dead code. As a positive control, a harmless const fn returning a constant, borrowed with a static assertion on the initializer main path, must still promote. These tests distinguish safe-path promotion from promotion anywhere in the body.
Cases: 121557-8436045e246c9a0b6d04e5e6ac8797055b20121b
Source: https://github.com/rust-lang/rust/pull/121557
> so we only promote such calls in basic blocks that are guaranteed
> Computes the sets of blocks of this MIR that are definitely going to be executed
> if the function returns successfully. That makes it safe to promote calls in them
> This calls a function or the destructor.
> Similar to above, we only consider successful execution.
> We do not promote function calls in `const` initializers in dead code.

### Collect required_consts before promotion and account for failing promoteds
Promotion can move a possibly failing const into a new promoted body, so required-const bookkeeping must happen before promotion rather than after it. The corrected flow collects required_consts before promotion, registers a promoted operand in the parent body when add_to_required is set, fills each promoted body's own required_consts, and re-filters inlined required consts after instantiation. Without this, a latent const-evaluation failure could be missed because the failing const was moved into a promoted body without the promoted operand or its required consts remaining reachable.
Preconditions: Promotion creates a new const operand that may fail to evaluate, especially when the promoted expression involves a const fn call.; The original body has required_consts that must remain accounted for after promotion.; Inlining followed by instantiate-and-normalize may turn required unevaluated consts into evaluated values, requiring a re-filter.
Pitfalls: Do not collect required_consts after promotion; the historical correction explicitly collects them before promotion so promoted consts remain accounted for in the outer body.; Only unevaluated consts need to be added to required_consts, because only those can still fail to evaluate.; When promotion creates a call-based promoted, set add_to_required and push the promoted operand into the parent's required_consts; otherwise a const moved into the promoted body can lose its failure.; Fill the promoted body's own required_consts so standalone evaluation cannot silently miss a failure.; After inlining, filter callee required_consts with is_required_const() before extending the caller because instantiate_and_normalize_erasing_regions may have evaluated some of them.
Test strategy: Exercise a failing associated const inside a dead branch of an #[inline(never)] generic function, called from main, under both -Copt-level=0 and -O revisions; expect E0080 constant-evaluation failure if the promoted required const is dropped. Also cover multiple failing const-fn bodies in dead code, such as overflow, division by zero, and out-of-bounds indexing, and verify build-pass when the promotion/required_consts accounting is correct.
Cases: 121557-8436045e246c9a0b6d04e5e6ac8797055b20121b
Source: https://github.com/rust-lang/rust/pull/121557
> Collect `required_consts` *before* promotion, so if there are any consts being promoted
> This promoted involves a function call, so it may fail to evaluate.
> Now that we did promotion, we know whether we'll want to add this to `required_consts`.
> Only unevaluated consts have to be added to `required_consts` as only those can possibly
> If promotion moved `C` from our required_consts to its own, without adding itself to
> because we are calling `instantiate_and_normalize_erasing_regions` -- so we filter again.

### PromoteTemps must reject every fake borrow variant
Fake borrows are borrowck-only artifacts and must never be promoted as ordinary shared borrows. When the fake-borrow kind gained a payload distinguishing shallow and deep forms, matching only the old exact BorrowKind::Fake became too narrow. For this pass, every BorrowKind::Fake(_) must be treated as unpromotable, alongside closure-capture mutable borrows. A companion cross-pass invariant, belonging to post-borrowck cleanup rather than promotion, is that all fake borrows must also be erased before runtime MIR; deref-pattern lowering specifically requires a deep fake borrow because shallow borrows do not protect projections from guard mutation.
Preconditions: The MIR contains an Rvalue::Ref whose borrow kind is Fake(_), either Shallow or Deep.; Promotion analysis encounters that fake borrow in a candidate body and must reject it rather than promoting it.; For the cross-pass invariant, post-borrowck cleanup must erase all fake borrows; this remains a cleanup responsibility, not a PromoteTemps responsibility.; For deref patterns, a guard can mutate through the dereferenced place, so deep fake-borrow protection is required.
Pitfalls: After the enum gains a payload, matching only BorrowKind::Fake is too narrow; use BorrowKind::Fake(_) so both shallow and deep fake borrows are rejected.; Do not treat deep fake borrows as ordinary promotable shared borrows merely because they look immutable or aliasable.; A shallow fake borrow protects only the immediately borrowed place, not its projections; deref patterns need a deep fake borrow to reject guard mutation such as writing through the dereferenced box.; Do not attribute fake-borrow erasure to promotion: cleanup must erase fake borrow assignments and fake reads, while promotion must refuse to promote them.
Test strategy: Add MIR coverage containing both Fake(Shallow) and Fake(Deep) borrows and check that post-borrowck cleanup replaces fake-borrow assignments and ForMatchGuard fake reads with nop; also check promotion rejects both fake-borrow kinds, since the supplied historical change lacks a dedicated promotion regression test. Add a deref-pattern UI case where a match guard writes through the dereferenced box and expect E0510 cannot assign in match guard, while keeping run-pass deref-pattern tests for branch/bindings. The paired behavior shows that with the deep fake borrow, an initial false scrutinee still sees the later deref-pattern match, whereas with only a shallow borrow the guard mutation can change the pointee and alter the selected arm.
Cases: 122598-726fb55ae29a778a698e1c880aa0ae46920ece88
Source: https://github.com/rust-lang/rust/pull/122598
> /// A shared shallow borrow. The immediately borrowed place must be immutable, but projections
> /// A shared (deep) borrow. Data must be immutable and is aliasable.
> This is used when lowering deref patterns, where shallow borrows wouldn't prevent something
> StatementKind::Assign(box (_, Rvalue::Ref(_, BorrowKind::Fake(_), _)))
> BorrowKind::Fake(_) | BorrowKind::Mut { kind: MutBorrowKind::ClosureCapture } => {
> //~^ ERROR cannot assign `*b` in match guard
