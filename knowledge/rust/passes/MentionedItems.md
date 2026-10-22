# MentionedItems
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not collect only monomorphic used items after optimization: dead-code elimination or inlining can remove the sole syntactic path to an item whose `required_consts` fail.
- Do not infer that every dead mention must produce an error; the requirement is specifically to evaluate `required_consts` of syntactically mentioned items, including failing constants.
- Do not assert that the mentioned set is a stable or soundness-critical guarantee; it is optimization-independent in intent, not stable API.
- Do not claim finite UI pairs prove universal equivalence; they are focused regression checks for the optimization-dependent acceptance behavior.
- Do not gather mentions only from constants whose type is already `ty::FnDef`; pre-monomorphization callees may be generic, opaque, or associated.
- Do not let the test helper generics be inlined when the goal is to retain a generic mention; use `#[inline(never)]` so the test exercises mention gathering rather than accidental monomorphization through inlining.
- Do not conflate function mentions, closure mentions, drops, and function-pointer coercions; each is a distinct syntactic path that must remain traversable before optimization.
- Do not classify every unsizing cast as vtable-producing.
- Do not treat every remaining unsize as automatically a vtable; retain the source/target trait and dyn-star checks.
- Do not use an array-to-slice/`str` unsizing case as a positive failure-const mention test when it should not create a vtable mention.
- Do not update `usage_map` for mention-only visits; update it only for used items.
- Do not allow duplicate mixed mention/use entries to interfere with usage tracking.
- Do not skip mention processing merely because an item was already visited as a used item; record used mentions before monomorphization so the skip is deliberate and correct.

## Patterns Not Well Handled

### Collect mentions before optimization so dead const-eval failures remain errors
MentionedItems must gather syntactic item mentions before optimization-level-dependent MIR passes and recursively evaluate the `required_consts` of those mentioned items. This makes a post-monomorphization const-eval failure visible even when the only syntactic path to the failing item is dead code that optimization would erase. The historical source-derived problem was acceptance of a program at `-O` while the same source failed at `-Copt-level=0`, because an optimization-first pass collected only optimized used items. The correction is to record `MentionedItems` before optimizations and, in mention mode, evaluate mentioned items even when they are no longer used.
Preconditions: `MentionedItems` runs before optimization-level-dependent passes and is enabled even at opt-level 0.; `CollectionMode::MentionedItems` evaluates `required_consts` and recursively processes `body.mentioned_items` without producing used items.; A failing generic item is reached only through a syntactic mention whose use can be removed by MIR optimization, such as dead code or a call/drop/coercion that optimization can eliminate.; The same source is compared under both `-Copt-level=0` and `-O` so optimization dependence is observable.
Pitfalls: Do not collect only monomorphic used items after optimization: dead-code elimination or inlining can remove the sole syntactic path to an item whose `required_consts` fail.; Do not infer that every dead mention must produce an error; the requirement is specifically to evaluate `required_consts` of syntactically mentioned items, including failing constants.; Do not assert that the mentioned set is a stable or soundness-critical guarantee; it is optimization-independent in intent, not stable API.; Do not claim finite UI pairs prove universal equivalence; they are focused regression checks for the optimization-dependent acceptance behavior.
Test strategy: Use UI revisions on the same source: `//@revisions: noopt opt`, `//@ build-fail`, `//@[noopt] compile-flags: -Copt-level=0`, `//@[opt] compile-flags: -O`, and mark the same `E0080` on the const line for both revisions rather than only on `noopt`. Build a minimal pair where the live-use program errors and the dead-use optimized program historically did not, then require both to fail after the fix. Keep a build-pass negative control for dead code that does not mention a failing const.
Cases: 122568-8c01b85dba15f83724949769d45929cc449a9cf9
Source: https://github.com/rust-lang/rust/pull/122568
> Fixes #107503
> This fails without optimizations, so it should also fail with optimizations.

### Mention traversal must cover erased syntactic paths and record callee types, not assumed DefIds
Mention gathering must mirror collector visiting across the syntactic constructs that can reference a generic or otherwise not-yet-monomorphized callee: `Call`, `Drop`, `InlineAsmOperand::SymFn`, unsizing/`DynStar`, `ReifyFnPointer`, and `ClosureFnPointer` casts. `MentionedItem::Fn` and `MentionedItem::Closure` must record a `Ty`, not a `DefId` plus args, because a generic, opaque, or associated callee may only become a `FnDef` or `Closure` after monomorphization. This preserves mentions that optimization could otherwise erase.
Preconditions: Mention gathering mirrors collector visiting for `Call`, `Drop`, inline-assembly `SymFn`, unsizing/`DynStar`, reified function pointers, closure-to-function-pointer coercions, and closures.; The relevant pre-optimization MIR mentions include `Fn(Ty)`, `Drop(Ty)`, `UnsizeCast { source_ty, target_ty }`, and `Closure(Ty)`.; The callee may be hidden behind a generic, opaque, or associated type and may only resolve to a `FnDef` or `Closure` during monomorphization.
Pitfalls: Do not gather mentions only from constants whose type is already `ty::FnDef`; pre-monomorphization callees may be generic, opaque, or associated.; Do not let the test helper generics be inlined when the goal is to retain a generic mention; use `#[inline(never)]` so the test exercises mention gathering rather than accidental monomorphization through inlining.; Do not conflate function mentions, closure mentions, drops, and function-pointer coercions; each is a distinct syntactic path that must remain traversable before optimization.
Test strategy: Add focused cases for direct dead calls, `Drop`/move, function-pointer reification, closure-to-function-pointer coercion, a const whose value contains a function pointer, inline-assembly `SymFn`, and a callee hidden behind a generic, opaque, or associated type. Compile each failing case in both `noopt` and `opt` revisions and require the same primary `E0080` const-eval error. Mark generic helpers `#[inline(never)]` so inlining cannot mask mention gathering.
Cases: 122568-8c01b85dba15f83724949769d45929cc449a9cf9
Source: https://github.com/rust-lang/rust/pull/122568
> They may become FnDef during monomorphization!
> Before doing anything, remember which items are being mentioned so that the set of items

### Only vtable-producing unsizing casts create mentions
Unsizing casts are relevant to MentionedItems only when they produce a vtable. The array-to-slice/`str` case is explicitly excluded, while other unsizing casts still need a target/source trait or dyn-star check to determine whether the cast is vtable-producing. This keeps mention gathering focused on casts that can refer to an item whose `required_consts` must be evaluated.
Preconditions: Unsizing mention analysis distinguishes casts that require vtables from casts that do not.; The array-to-slice/`str` case is excluded from vtable-producing unsizing.; For remaining unsize cases, `visit_mentioned_item` checks target trait/dyn-star versus source trait/dyn-star and is only interested in casts that produce a vtable.
Pitfalls: Do not classify every unsizing cast as vtable-producing.; Do not treat every remaining unsize as automatically a vtable; retain the source/target trait and dyn-star checks.; Do not use an array-to-slice/`str` unsizing case as a positive failure-const mention test when it should not create a vtable mention.
Test strategy: Include a vtable-producing unsizing case whose mentioned item has a failing post-monomorphization constant, compiled in both `noopt` and `opt` revisions with the same primary `E0080` error. Pair it with an array-to-slice/`str` unsizing case as a negative control to verify it is not classified as vtable-producing.
Cases: 122568-8c01b85dba15f83724949769d45929cc449a9cf9
Source: https://github.com/rust-lang/rust/pull/122568
> We need to detect unsizing casts that required vtables.
> This fails without optimizations, so it should also fail with optimizations.

### Keep used-item and mentioned-item collection state distinct
`MentionedItems` distinguishes `CollectionMode::UsedItems` from `CollectionMode::MentionedItems`. In mention mode, the pass evaluates `required_consts` and recursively processes `body.mentioned_items` without producing used items. Used-item traversal records `used_mentioned_items` before monomorphizing so mention processing can skip items already fully visited as used items. `usage_map` is updated only for used items because the usage-map logic does not like duplicate mixed mention/use entries.
Preconditions: The collector has separate `CollectionMode::UsedItems` and `CollectionMode::MentionedItems` behavior.; Mention mode recursively processes `body.mentioned_items` and evaluates `required_consts` without producing used items.; Used-item traversal records `used_mentioned_items` before monomorphizing.
Pitfalls: Do not update `usage_map` for mention-only visits; update it only for used items.; Do not allow duplicate mixed mention/use entries to interfere with usage tracking.; Do not skip mention processing merely because an item was already visited as a used item; record used mentions before monomorphization so the skip is deliberate and correct.
Test strategy: Exercise inputs where the same item is reachable both as a used item and as a mention, and verify the pass still reports the expected primary const-eval error without duplicate or usage-map interference. Use `noopt`/`opt` revisions to confirm the mention-mode behavior remains optimization-independent, and retain a negative control where no failing const is mentioned.
Cases: 122568-8c01b85dba15f83724949769d45929cc449a9cf9
Source: https://github.com/rust-lang/rust/pull/122568
> Before doing anything, remember which items are being mentioned so that the set of items
> visit_mentioned_item
