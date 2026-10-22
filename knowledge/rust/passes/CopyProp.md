# CopyProp
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Checking borrowedness only on the local currently being replaced is insufficient; the merge decision must be made when classes are formed.
- The rule is not 'never merge borrowed with non-borrowed'. Under this historical rule, merging a non-borrowed local into a borrowed class is explicitly allowed; only merging two classes that both contain a borrowed member is forbidden.
- Do not reduce the condition to a per-use skip or to a check on one endpoint; the invariant is about both classes being joined.
- The invariant `borrowed_classes.contains(head) == any member of the class is borrowed` must hold for every class, as asserted in debug builds.
- Removing a per-use borrowed-local guard is safe only after class formation itself prevents invalid merges.
- The historical defect is specifically `&&` ('both borrowed'); the corrected invariant is `||` ('either borrowed').
- Do not describe this as introducing a new rewrite; it blocks an unsound optimization and retains copy assignments.
- A borrow alone and a post-copy overwrite are separate conditions. The guard forbids unification whenever either endpoint is borrowed; observability of the wrong result often requires a write through the borrow before the propagated value is read.
- Removing `_x = copy _y` lines from expected MIR is evidence of the old, unsound propagation; retaining the copy is the corrected output, not an optimization failure.
- Expected MIR changes in other tests (for example `write_to_borrowed` and `pre-codegen/slice_filter`) are consequences of the stricter guard, not evidence that the replacement behavior is wrong.
- Copied value equality does not capture the address-identity failure: the value component can be unchanged while the address component differs.
- A retained test name or old comment does not establish that the previous pass output is correct; compare actual value assignments and uses in decoded MIR revisions.
- Do not treat `CHECK-NOT` on assignments as universal proof. It is a focused guard for the region where an assignment to a borrowed local must not appear.
- For write-through cases, the post-copy overwrite is what exposes the stale read; for two-borrowed cases, the separate storages are what expose the address change. Keep the conditions separate.

## Patterns Not Well Handled

### Track borrowedness when forming CopyProp copy equivalence classes, not only when replacing uses
For CopyProp, copy equivalence classes built from copy/move assignments must carry a class-level borrowedness fact. The historical implementation merged classes without regard to borrowed locals and then skipped replacement of individual borrowed locals during the visit. That late guard could not undo a class merge: two distinct borrowed storages could be unified, and a non-borrowed local copying one of them could be rewritten to the shared representative. The corrected class-formation rule forbids merging two classes when both already contain a borrowed member, while still allowing a non-borrowed local to join a class that contains a borrowed local. This rule is distinct from the later either-side guard; do not conflate them.
Preconditions: CopyProp runs `SsaLocals::new` and `compute_copy_classes` on a MIR body.; At least two locals are borrowed and connected by a copy chain, e.g. `_5 = copy _3` where both `_3` and `_5` are borrowed.; A non-borrowed local may copy one of the borrowed locals and be used later.; Address identity of the borrowed locals is observable through references or raw pointers.; The borrowedness bitset is keyed by class head and must remain true for a class if any member is borrowed, including when a non-borrowed local joins and when the `RETURN_PLACE` head is renamed.
Pitfalls: Checking borrowedness only on the local currently being replaced is insufficient; the merge decision must be made when classes are formed.; The rule is not 'never merge borrowed with non-borrowed'. Under this historical rule, merging a non-borrowed local into a borrowed class is explicitly allowed; only merging two classes that both contain a borrowed member is forbidden.; Do not reduce the condition to a per-use skip or to a check on one endpoint; the invariant is about both classes being joined.; The invariant `borrowed_classes.contains(head) == any member of the class is borrowed` must hold for every class, as asserted in debug builds.; Removing a per-use borrowed-local guard is safe only after class formation itself prevents invalid merges.
Test strategy: Add a custom-MIR CopyProp test under `tests/mir-opt/copy-prop/` with `//@ test-mir-pass: CopyProp` and `// EMIT_MIR write_to_borrowed.main.CopyProp.diff`. Borrow two locals connected by a copy (`_3 = const 'b'; _5 = copy _3; _6 = &_3; _4 = copy _5; ...; _6 = &_5; Call(_7 = dump_var(_4))`). Use `CHECK-NEXT` to assert `_5 = copy _3` survives, the call is `dump_var::<char>(copy _5)`, and `_4 = copy _5` is removed; use `CHECK-NOT: {{_.*}} = {{_.*}};` in the relevant region to ensure no assignment to a borrowed local is introduced. Program-level differential testing should compare address identity for two distinct live borrowed locals, not merely copied value equality.
Cases: 142571-c4b67c6d873866d4b2c687306bf2f558a8659246
Source: https://github.com/rust-lang/rust/pull/142571
> This PR fixes it by forbidding the unification of two *classes* if any of those contain a borrowed local.
> This bitset is keyed by *class head* and contains whether any member of
> Do not unify two borrowed locals.
> borrowed_classes.insert(head);
> // Invariant: `borrowed_classes` must be true if any member of the class is borrowed.
> _5 = copy _3
> The current implementation of `CopyProp` avoids unifying two borrowed locals, as this would change the result of address comparison.

### Reject a copy-class unification when either endpoint is borrowed (`&&` to `||`)
A subsequent historical CopyProp/SSA copy-class guard rejected unification only when BOTH `local` and `head` were borrowed (`&&`). The corrected guard rejects unification when EITHER endpoint is borrowed (`||`). This is a conservative restriction of the optimization, not a new rewrite: copies into or out of a borrowed local are retained so that a later write through the borrow cannot make a propagated read stale. The fix is qualified by the absence of an aliasing model: because a borrowed local may be written before the borrow is read again, unification of borrowed locals is forbidden outright.
Preconditions: CopyProp is optimizing a MIR function and considering merging `local` with `head = copies[rhs]` for a copy assignment.; At least one of `local` and `head` has its address taken / is in `borrowed_classes`; the historical `&&` guard skipped only when both were borrowed.; The non-borrowed side may be read later, and the borrowed side may be written through its reference before that read.; In loop-shaped cases, the borrow may be re-established through a backedge and read on the next iteration.
Pitfalls: The historical defect is specifically `&&` ('both borrowed'); the corrected invariant is `||` ('either borrowed').; Do not describe this as introducing a new rewrite; it blocks an unsound optimization and retains copy assignments.; A borrow alone and a post-copy overwrite are separate conditions. The guard forbids unification whenever either endpoint is borrowed; observability of the wrong result often requires a write through the borrow before the propagated value is read.; Removing `_x = copy _y` lines from expected MIR is evidence of the old, unsound propagation; retaining the copy is the corrected output, not an optimization failure.; Expected MIR changes in other tests (for example `write_to_borrowed` and `pre-codegen/slice_filter`) are consequences of the stricter guard, not evidence that the replacement behavior is wrong.
Test strategy: Add CopyProp MIR-opt tests with `// EMIT_MIR ...CopyProp.diff` that pin conservative output. For a borrowed argument, assert `_2 = copy _1;` is retained and the call uses `copy _2`, not `copy _1`. For a local borrowed after copying, assert `_4 = copy _5;` remains and the later call reads `_4`. For loop-carried aliasing, use `let mut c; let mut p = &false; loop { let a = !*p; let b = !*p; c = a; p = &c; if a != b { return; } }`; assert address-taking never targets `a` or `b` (`// CHECK-NOT: &[[a]]`, `// CHECK-NOT: &[[b]]`) and does target `c` (`// CHECK: &[[c]]`). Run panic-abort and panic-unwind MIR dumps. These finite regression checks pin the guard; they do not by themselves prove general equivalence.
Cases: 143509-b1fdb4bdc8818aced53e46a34a3e92cfcfcc8ece, 143757-83c0a8c833631c24fb849e5e7a1790d0d36db58f
Source: https://github.com/rust-lang/rust/pull/143509
Source: https://github.com/rust-lang/rust/pull/143757
> Do not unify borrowed locals in CopyProp.
> Instead of trying yet another scheme to unify borrowed locals in CopyProp, let's just stop trying. We had already enough miscompilations because of this.
> -        if borrowed_classes.contains(local) && borrowed_classes.contains(head) {
> +        if borrowed_classes.contains(local) || borrowed_classes.contains(head) {
> We must not unify a borrowed local with another that may be written-to before the borrow is
> As we have no aliasing model yet, this means forbidding unifying borrowed locals.
> // CHECK-NEXT: _2 = copy _1;
> // CHECK-NEXT: _0 = opaque::<T>(copy _2)
> // CHECK-NEXT: _4 = copy _5;
> fn borrow_in_loop() {
> // CHECK-NOT: &[[a]]
> // CHECK: &[[c]]

### Observe borrowed-local copy unification through address identity or write-through, and test both failure modes
Borrowed-local unification is observable in two distinct ways. In the two-borrowed-locals case, conflating two distinct borrowed storages changes address comparison: the copied value remains the same but the address-identity component differs. In the either-side case, a borrowed local may be written through its reference after the copy and before the propagated read; replacing the copied local with the borrowed local makes the read observe the later value instead of the value at copy time. Regression tests should target these distinct observables rather than only checking that some copy was removed or retained.
Preconditions: There is a copy assignment whose endpoints participate in, or are candidates for, a CopyProp equivalence class.; For address identity: two distinct live borrowed locals are connected by a copy chain, and their addresses are compared or otherwise distinguished.; For write-through: exactly one endpoint is borrowed, the copy snapshots a value, and the borrowed local is written through its reference before the copied value is read again.; A non-borrowed local may copy the borrowed local and later be used, so an incorrect class representative changes the read.
Pitfalls: Copied value equality does not capture the address-identity failure: the value component can be unchanged while the address component differs.; A retained test name or old comment does not establish that the previous pass output is correct; compare actual value assignments and uses in decoded MIR revisions.; Do not treat `CHECK-NOT` on assignments as universal proof. It is a focused guard for the region where an assignment to a borrowed local must not appear.; For write-through cases, the post-copy overwrite is what exposes the stale read; for two-borrowed cases, the separate storages are what expose the address change. Keep the conditions separate.
Test strategy: Use MIR-opt diffs plus program-level differential pairs. For the two-borrowed case, assert `_5 = copy _3` survives, `_4 = copy _5` is removed, and the call uses `copy _5`; compare addresses of two live borrowed locals so the original yields false and the collapsed-storage variant yields true. For the write-through case, assert `_4 = copy _5` survives and the call reads `_4`; compare a snapshot taken before `*r = new_value` with the later read, so the original returns the snapshot value and the collapsed-use variant returns the newly written value. Use varied inputs such as `(seed,new_value)` pairs; finite concrete tests are regression evidence, not a general equivalence proof.
Cases: 142571-c4b67c6d873866d4b2c687306bf2f558a8659246, 143509-b1fdb4bdc8818aced53e46a34a3e92cfcfcc8ece, 143757-83c0a8c833631c24fb849e5e7a1790d0d36db58f
Source: https://github.com/rust-lang/rust/pull/142571
Source: https://github.com/rust-lang/rust/pull/143509
Source: https://github.com/rust-lang/rust/pull/143757
> _5 = copy _3
> // CHECK-NOT: {{_.*}} = {{_.*}};
> +-         _4 = copy _5;
> ++         _7 = dump_var::<char>(copy _5) -> [return: bb1, unwind unreachable];
> We must not unify a borrowed local with another that may be written-to before the borrow is
> // CHECK-NEXT: _4 = copy _5;
> // CHECK-NEXT: _7 = dump_var::<char>(copy _4)
> if borrowed_classes.contains(local) && borrowed_classes.contains(head)
> _4 = copy _5
> _1 = copy _6
> let mut p = &false;
> // CHECK-NOT: &[[a]]
> // CHECK: &[[c]]
> fn borrow_in_loop() {
> // EMIT_MIR borrowed_local.borrow_in_loop.CopyProp.diff
