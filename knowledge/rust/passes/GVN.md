# GVN
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not identify two structurally equal `Value`s without their `Ty`; they are not interchangeable.
- Do not reconstruct aggregate, raw-pointer, cast, or projection types from the value representation; use the stored type.
- Do not compute layouts for non-scalar types inside a coroutine; the guard is `let ty = if !self.is_coroutine || ty.is_scalar() {`.
- Handle ZSTs before interpreting structural contents, and derive `PtrMetadata` from the tracked pointer type; a thin pointer's metadata may fold to `()` while a wide pointer's metadata is `usize`.
- Only mark an SSA local reusable when the local type and assigned rvalue type match exactly.
- Do not route opaque values, addresses, or non-deterministic constants through the deduplicating insertion path.
- Do not merge two mentions of the same non-deterministic constant; each needs a different disambiguator.
- Do not merge borrows or pointers; each needs a different provenance.
- `insert_unique` stores a placeholder hash and does not add the index to the hash table; later deduplication must not find it.
- Do not conclude that the pre-change code was miscompiling: the historical concern was wasted hashing, while the unique counter preserved distinctness. The reusable correctness rule is that unique values must not be deduplicated.
- Do not use the `Coroutine` arm for `CoroutineClosure`; the source notes coroutines are never ZST, while an empty-field coroutine-closure aggregate is handled as ZST in GVN.
- Do not omit `CoroutineClosure` from def-like aggregate handling; it is a closure aggregate, not a state-machine coroutine.
- Const-prop and ABI rules also classify coroutine-closures with closures, but those are adjacent MIR consumers; keep GVN's decision focused on ZST and aggregate identity.
- Do not fold `NullOp::DebugAssertions` in GVN or const-prop before monomorphization; the folded value would reflect the defining crate's setting, not the caller's.
- Do not guard unsafe-precondition checks with expansion-time `cfg!(debug_assertions)`; the guard must survive into MIR and be resolved at codegen/monomorphization.
- Do not make the runtime precondition check generic; it is intentionally monomorphic, `#[inline(never)]`, and `#[rustc_nounwind]`.
- MIR tests are sensitive to debug assertions and panic strategy; new checks add `cfg!(debug_assertions)` branches and `precondition_check` calls.
- Do not attribute the root cause to GVN itself: the bogus constant originates in const eval deciding a generic `FnDef` was monomorphic enough; GVN only folds the resulting constant comparison.
- Do not expect corrected MIR to evaluate or fold the comparison; the fix intentionally leaves the generic `Eq` in place.
- The outer `ty.has_param()` check is insufficient if the visitor does not recurse into `FnDef`/closure/coroutine substs.
- A `.diff` showing identical before/after GVN MIR is expected corrected behavior here, not evidence that the test is vacuous.
- Do not eliminate a cast that removes metadata, such as `*const [T] -> *const T`; it changes metadata from `usize` to `()` and must remain.
- Do not compare only tail types when known metadata types differ; known metadata equality and unknown-tail equality are distinct.
- Do not fold `PtrMetadata` for casts other than an array-to-slice unsizing cast.
- Do not strip an address/reborrow whose projection is not exactly a single `Deref`.
- Do not remove comparison casts merely because both sides are `PtrToPtr`; different source types and fat-to-thin casts must remain.
- Do not collapse `PtrToPtr`-then-`Transmute` when the cast was fat-to-thin and changed pointer size/layout.
- GVN runs on possibly generic MIR; syntactic metadata comparison alone can miss valid normalization cases.
- Do not treat a slice's length as the source array's length when a subslice or runtime slice creation is involved.
- Do not treat `Len` and `PtrMetadata` as interchangeable for optimization: one consumes a place, the other a pointer value.
- Do not drop projection/type guards; GVN must fall back to a symbolic `Value::Len` and DataflowConstProp to top when the place shape is not understood.
- Do not assume a length for partially initialized or unknown aggregates.
- Do not emit `PtrMetadata` in pre-runtime MIR; the Validator rejects it outside runtime MIR.
- Do not collapse aggregates merely because fields look like projections of one base; different nominal types, swapped fields, mutated bases, and mismatched enum variants must block the rewrite.
- Do not allow complex LHS projections unconditionally; doing so can create `*a = copy (*b)` where source and destination may alias and the assignment overlaps.
- Do not create assignments between different fields of the same local.
- Copying an existing aggregate value is not equivalent to constructing the aggregate when the source place can be mutated through an alias before use.
- The old code could return `Some(value)` even when it did not rewrite the rvalue; 'recognized as copyable' is not the same as 'rvalue was actually rewritten'.
- The historical fix did not revert the implementation; it marked the optimization unsound and gated tests with `-Zunsound-mir-opts`.
- Do not conflate `T: Freeze` with stability of the storage holding a shared reference; the reference itself may be mutated through unsafe aliasing.
- Do not treat every deref reuse as wrong: derefs can still be reused inside uninterrupted regions.
- Only `SwitchInt` and `Goto` are safe terminators for preserving derefs; calls and ASM must invalidate.
- Do not assume reverse postorder is topological once loops exist; a not-yet-processed loop-body statement or terminator may have performed an indirect write.
- For loop headers, invalidate before visiting the header's data, and mark a block visited only after checking successors so self-loops are handled.
- The negative directive in the historical loop test is misspelled `// CEHCK-NOT: copy (*[[VAL_REF]]);`; a focused test should spell it correctly or the negative assertion will silently not run.
- Do not equate an `Index` projection's local-place identity with the index value; the local may be overwritten after the borrow is formed.
- Do not blanket-disable all repeat-index simplification; the local case may still optimize to a repeated local while the place case retains the dereference.
- An SSA/non-SSA guard alone is insufficient if the address still stores a raw place rather than the index's `VnIndex`.
- Being an SSA local does not guarantee its value at an arbitrary later location matches its value where the pointee was borrowed.
- Flattening through `ProjectionElem::Index` can create places referring to non-existing locals or use stale index values.
- Do not treat `Deref` as an ordinary projection that can be freely followed by additional projections during reconstruction.
- Returning `Some(place)` with projections after `Deref` yields an ill-formed place even if the value graph otherwise type-checks.
- The supplied patch contains only the compiler change and no regression-test hunk; do not infer a test from it.
- Using only `predicates_of(...).predicates` omits parent predicates; for this precondition the pass must use the instantiated identity predicate set.
- Do not feed clauses with unevaluated const projections into the impossibility check; the source says they cause cycles.
- Error-referencing predicates must short-circuit before const evaluation.
- Clearing the body intentionally degrades diagnostics to `error[E0080]: entering unreachable code`; that message change is not a GVN correctness regression.
- Moving crash repros to UI tests with `//@ build-pass` is part of the coverage; an old test expecting the old ICE message will not verify the unreachable marking.
- Nested paths are a sum of per-hop calls; folding only the first call is wrong. For `offset_of!(Alpha, z.0)`, expect `offset_of::<Alpha>(...)` plus `offset_of::<Beta>(...)` and an `AddWithOverflow`.
- Do not fold a generic const block such as `const generic::<T>::{constant#0}` to a concrete offset.
- `Rvalue::NullaryOp` no longer carries a `Ty`; visitors and type checkers that previously visited a nullary operand type must stop doing so.
- The new `offset_of` intrinsic is only for const evaluation; LLVM codegen refuses to generate code for it, and it is wrapped in a const block.
- Const checking only honors `span.allows_unstable` when the callee is const-stable; do not bypass recursive stability.
- Do not merge reifications in GVN merely because their target types look identical; each reification of a generic fn may get a different pointer.
- Do not drop `ReifyFnPointer` casts from MentionedItems; they are item mentions.
- Do not assume source and target safety are equal; safe fn items may coerce to unsafe fn pointers, but unsafe fn items may not coerce to safe fn pointers.
- Do not match only one safety payload; match `ReifyFnPointer(_)` so both safe and unsafe reifications are handled.
- Do not attribute the separate HIR coercion inference-variable leak to GVN; its regression test exercises HIR coercion.

## Patterns Not Well Handled

### GVN values are typed: intern (Value, Ty) and avoid layout reconstruction
GVN's symbolic value identity must include the MIR type. The historical foil is type-erasing CSE: treating a structural `Value` alone as complete identity, reusing it in a context with another type, and reconstructing aggregate/raw-pointer/cast/projection types from the value shape before evaluating layouts. Store the `Ty` alongside the value, read types back from it, fold typed ZSTs before interpreting contents, and avoid computing non-scalar layouts inside coroutine bodies because that can cause query cycles. `PtrMetadata` metadata must likewise come from the stored pointer type, not be recovered structurally.
Preconditions: GVN runs on the MIR body, either through normal optimization or an explicit MIR-pass test.; The body contains structurally equal values at different MIR types, or a type whose layout must not be recomputed during GVN evaluation.; For coroutine-layout hazards, the body is a coroutine/async body, including malformed bodies reached during error recovery.; For nonsensical-bound hazards, the body contains trivial or nonsensical bounds such as `str: Sized`.
Pitfalls: Do not identify two structurally equal `Value`s without their `Ty`; they are not interchangeable.; Do not reconstruct aggregate, raw-pointer, cast, or projection types from the value representation; use the stored type.; Do not compute layouts for non-scalar types inside a coroutine; the guard is `let ty = if !self.is_coroutine || ty.is_scalar() {`.; Handle ZSTs before interpreting structural contents, and derive `PtrMetadata` from the tracked pointer type; a thin pointer's metadata may fold to `()` while a wide pointer's metadata is `usize`.; Only mark an SSA local reusable when the local type and assigned rvalue type match exactly.
Test strategy: Use focused MIR-opt tests with explicit GVN `CHECK`/diff expectations. Pair the same structural ZST at different types (for example `()` and a `repr(align(16))` ZST) and assert they are not merged. Check ZST transmute expectations such as `const ZeroSized: Never`, and `PtrMetadata` thin-versus-wide expectations. Add malformed coroutine and nonsensical-bound repros compiled with GVN enabled, expecting no ICE. These are MIR/diagnostic expectations, not universal equivalence proofs.
Cases: 143271-4a95b165274f9de5c6a0d3c13ae3103e2ac23eb9
Source: https://github.com/rust-lang/rust/pull/143271
> MIR is fully typed, so type information is an integral part of what defines a value.
> values: FxIndexSet<(Value<'tcx>, Ty<'tcx>)>,
> Avoid computing layouts inside a coroutine, as that can cause cycles.
> let ty = if !self.is_coroutine || ty.is_scalar() {
> // CHECK: = const ZeroSized: Never;
> // Metadata usize -> (), do not optimize.

### Unique-by-construction GVN values bypass deduplication
GVN creates some root values that must never be unified with another: opaque values, borrows/pointers with distinct provenance, non-deterministic constants, and deref invalidation results. The historical implementation hashed and equality-checked these in an `FxIndexSet` even though a fresh counter already guaranteed uniqueness. The reusable invariant is the inverse generalization: send unique-by-construction values through an insertion path that always makes a fresh `VnIndex` without hashing/deduplication, and allow only deterministic, genuinely deduplicable values through ordinary `insert`.
Preconditions: `ValueSet::insert_unique` is restricted to `Value::Opaque`, `Value::Address`, or `Value::Constant { disambiguator: Some(_), .. }`.; `ValueSet::insert` is restricted to non-opaque, non-address values and deterministic constants with `disambiguator: None`.; `VnOpaque` is constructed only by `insert_unique`, and its `Hash`/`PartialEq` are intentionally `unreachable!()` so accidental hashing or comparison ICEs.; A non-deterministic constant's disambiguator differs per mention; borrow/pointer provenance differs per borrow/pointer.; `forget` replaces a stored value with `Value::Opaque(VnOpaque)` in place rather than inserting a new value.
Pitfalls: Do not route opaque values, addresses, or non-deterministic constants through the deduplicating insertion path.; Do not merge two mentions of the same non-deterministic constant; each needs a different disambiguator.; Do not merge borrows or pointers; each needs a different provenance.; `insert_unique` stores a placeholder hash and does not add the index to the hash table; later deduplication must not find it.; Do not conclude that the pre-change code was miscompiling: the historical concern was wasted hashing, while the unique counter preserved distinctness. The reusable correctness rule is that unique values must not be deduplicated.
Test strategy: Unit-test `ValueSet` semantics: two `insert_unique` opaque insertions produce different indices and are not retrievable by later `insert`; separate non-deterministic constants produce different indices; the same deterministic constant deduplicates; different address provenance stays distinct; `forget(index)` makes the value opaque and prevents deduplication against the old value. Also construct MIR with two non-deterministic constant mentions and two distinct borrows/pointers, run GVN, and assert no common value is propagated. The supplied patch added no regression test diff, so these are proposed focused tests.
Cases: 145737-df04be8cf744b500b5972fdc76898a96067d5517
Source: https://github.com/rust-lang/rust/pull/145737
> GVN generates values that are not meant to be unified with any other. For instance `Opaque` (aka we don't know anything), non-deterministic constants and borrows.
> The current algorithm generates a unique index, so the generated `Value` will be different from all the existing.
> This is wasteful, as we should not hash that `Value` at all.
> This always creates a new `VnIndex`.
> so assign a different `disambiguator` to ensure they do not get the same `VnIndex`.

### Closure-like CoroutineClosure aggregates follow the Closure policy, not the Coroutine policy
A newly introduced coroutine-closure is closure-like, not coroutine-like. In GVN, an empty-field `CoroutineClosure` aggregate must be treated as a ZST and included in def-like aggregate handling, as closures are, rather than inheriting coroutine semantics. The historical counterfactual routes `CoroutineClosure` through the adjacent `Coroutine` policy, so an empty-field coroutine-closure aggregate is not ZST and is omitted from the def-like aggregate key. The same policy distinction appears in other MIR consumers, but GVN's reusable concern is the ZST/aggregate classification.
Preconditions: The program uses an async closure, producing `TyKind::CoroutineClosure` and `AggregateKind::CoroutineClosure`.; GVN runs over that coroutine-closure body or aggregate.; Tests distinguish zero-upvar coroutine closures from coroutines; coroutines are never ZST, but a zero-field coroutine-closure aggregate is closure-like.
Pitfalls: Do not use the `Coroutine` arm for `CoroutineClosure`; the source notes coroutines are never ZST, while an empty-field coroutine-closure aggregate is handled as ZST in GVN.; Do not omit `CoroutineClosure` from def-like aggregate handling; it is a closure aggregate, not a state-machine coroutine.; Const-prop and ABI rules also classify coroutine-closures with closures, but those are adjacent MIR consumers; keep GVN's decision focused on ZST and aggregate identity.
Test strategy: Build MIR-focused tests for async closures with and without captures, then inspect MIR after GVN: the zero-field `AggregateKind::CoroutineClosure` should follow the closure ZST path and be keyed as a def-like aggregate. Include `Closure` and `Coroutine` zero-field controls that must remain identical. Inspect emitted MIR rather than claiming execution semantics.
Cases: 120361-ed7fca1f8805b4348b801f23f444e0dda42f7aed
Source: https://github.com/rust-lang/rust/pull/120361
> | AggregateKind::CoroutineClosure(did, substs)
> | AggregateKind::CoroutineClosure(..) => true,
> // Coroutines are never ZST, as they at least contain the implicit states.
> | ty::CoroutineClosure(..)

### Do not fold runtime debug-assertion NullOps before monomorphization
The `debug_assertions()` intrinsic lowers to `Rvalue::NullaryOp(NullOp::DebugAssertions, bool)`. GVN must return `None` for that NullOp and leave it for codegen, which reads the monomorphizing caller's `sess.opts.debug_assertions`. Folding it during MIR const-prop or GVN would bake in the defining library's debug-assertion setting and can delete checks the caller requested.
Preconditions: `LowerIntrinsics` rewrites a call to `sym::debug_assertions` only when a target block is present, pushing `Rvalue::NullaryOp(NullOp::DebugAssertions, tcx.types.bool)` and turning the terminator into `Goto { target }`.; The intrinsic is registered as safe, takes no arguments, and returns `bool`.; Every MIR producer/consumer handles the new NullOp, including validation, pretty-printing, StableMIR, clippy const-fn qualification, and codegen.; GVN returns `None` for `NullOp::DebugAssertions`; the interpreter deliberately evaluates it to `false` because it performs the relevant checks itself.
Pitfalls: Do not fold `NullOp::DebugAssertions` in GVN or const-prop before monomorphization; the folded value would reflect the defining crate's setting, not the caller's.; Do not guard unsafe-precondition checks with expansion-time `cfg!(debug_assertions)`; the guard must survive into MIR and be resolved at codegen/monomorphization.; Do not make the runtime precondition check generic; it is intentionally monomorphic, `#[inline(never)]`, and `#[rustc_nounwind]`.; MIR tests are sensitive to debug assertions and panic strategy; new checks add `cfg!(debug_assertions)` branches and `precondition_check` calls.
Test strategy: Use mir-opt `EMIT_MIR` diffs for `DataflowConstProp` and GVN: the expected MIR keeps `_8 = cfg!(debug_assertions); switchInt(move _8) -> ...` and a `precondition_check` call rather than replacing the NullOp with a constant. Add UI `run-fail` tests with `-Copt-level=3 -Cdebug-assertions=yes` matching messages such as `unsafe precondition(s) violated: slice::from_raw_parts`. For codegen disappearance, pin `-Cdebug-assertions=no`. These are historical test directives, not proof of universal codegen equivalence.
Cases: 120594-dbf817bae1f25f0fa2fbb1e40ab74afc892d9a60
Source: https://github.com/rust-lang/rust/pull/120594
> Adds a new intrinsic, `debug_assertions` which is lowered to a new MIR NullOp, and only to a constant after monomorphization
> Rvalue::NullaryOp(NullOp::DebugAssertions, tcx.types.bool),
> NullOp::DebugAssertions => return None,
> let val = bx.tcx().sess.opts.debug_assertions;
> if ::core::intrinsics::debug_assertions() {
> _8 = cfg!(debug_assertions);

### Do not const-fold comparisons while generic FnDef/closure substs remain uninstantiated
Const eval's monomorphization guard must reject any type containing parameters, including parameters nested inside `FnDef`, closure, coroutine, or coroutine-closure substs. The historical visitor change skipped recursing into those substs, so `generic::<T>` was treated as monomorphic enough, `type_id` was evaluated for an uninstantiated generic item, and GVN folded the comparison to a fixed boolean. The corrected GVN behavior leaves `Eq(const ...<T>..., const ...<T>...)` in place because the constants are too generic.
Preconditions: The enclosing function is generic, for example `fn cursed_is_i32<T: 'static>() -> bool`.; The const expression depends on a generic parameter via `std::intrinsics::type_id::<T>()` or an equivalent const-eval intrinsic.; The generic parameter is nested inside a function item/closure/coroutine type such as `generic::<T>` rather than appearing as a direct `ty::Param`.; GVN runs, for example with `-C opt-level=2`.
Pitfalls: Do not attribute the root cause to GVN itself: the bogus constant originates in const eval deciding a generic `FnDef` was monomorphic enough; GVN only folds the resulting constant comparison.; Do not expect corrected MIR to evaluate or fold the comparison; the fix intentionally leaves the generic `Eq` in place.; The outer `ty.has_param()` check is insufficient if the visitor does not recurse into `FnDef`/closure/coroutine substs.; A `.diff` showing identical before/after GVN MIR is expected corrected behavior here, not evidence that the test is vacuous.
Test strategy: Add a MIR-opt regression test with `//@ test-mir-pass: GVN`, `//@ compile-flags: -C opt-level=2`, `#![feature(core_intrinsics)]`, a `fn generic<T>() {}`, a const fn calling `std::intrinsics::type_id::<T>()`, and a generic `cursed_is_i32<T: 'static>()` comparing `type_id_of_val(&generic::<T>)` with `type_id_of_val(&generic::<i32>)`. Require `_0 = Eq(const cursed_is_i32::<T>::{constant#0}, const cursed_is_i32::<T>::{constant#1});` followed by `return;`, i.e. no folded boolean. This is a focused regression expectation, not execution proof.
Cases: 136839-c1da4f1d3c4fc4beb5edcfa8a303a1dcbe27b65e
Source: https://github.com/rust-lang/rust/pull/136839
> When polymorphization got removed, this got changed to always treat all parameters as polymorphic and never recurse into them
> This is clearly wrong and can cause MIR opts to misbehave, for example this currently prints "false" in release mode:
> ty::Closure(..) | ty::CoroutineClosure(..) | ty::Coroutine(..) | ty::FnDef(..)
> if ty.has_param() {
> throw_inval!(TooGeneric);
> _0 = Eq(const cursed_is_i32::<T>::{constant#0}, const cursed_is_i32::<T>::{constant#1});

### Simplify pointer casts only when pointee metadata is preserved
GVN may look through pointer casts around `PtrMetadata`, pointer comparisons, and `Transmute` only when the cast preserves the pointee metadata type/tail. For `PtrMetadata`, it may strip metadata-preserving `PtrToPtr` casts and simple address/deref reborrows, and may fold an array-to-slice unsizing cast to the array length. For pointer comparisons, it may remove matching `PtrToPtr` casts on both sides only when the source pointer types are identical and metadata matches. For `Transmute` over `PtrToPtr`, it may collapse the cast only if metadata, and therefore pointer size, is unchanged. Nested `PtrToPtr` composition may skip an intermediate cast only when the inner source equals the outer target.
Preconditions: `PtrMetadata` is allowed in Runtime MIR and accepts both raw pointers and references.; A `PtrToPtr` cast may be skipped only when `ptr_metadata_ty_or_tail` for the source and target agree, comparing known metadata types or, when metadata is unknown, tail types.; An address/reborrow may be skipped only when its place is exactly `PlaceRef { local, projection: [PlaceElem::Deref] }` and the local has a value number.; Constant-length folding requires `CastKind::PointerCoercion(PointerCoercion::Unsize)` from an array pointee to a slice pointee with known array length.; Pointer comparison cast removal requires `lhs_from == rhs_from` and `pointers_have_same_metadata(*lhs_from, lhs_ty)`, including normalization for generic metadata.
Pitfalls: Do not eliminate a cast that removes metadata, such as `*const [T] -> *const T`; it changes metadata from `usize` to `()` and must remain.; Do not compare only tail types when known metadata types differ; known metadata equality and unknown-tail equality are distinct.; Do not fold `PtrMetadata` for casts other than an array-to-slice unsizing cast.; Do not strip an address/reborrow whose projection is not exactly a single `Deref`.; Do not remove comparison casts merely because both sides are `PtrToPtr`; different source types and fat-to-thin casts must remain.; Do not collapse `PtrToPtr`-then-`Transmute` when the cast was fat-to-thin and changed pointer size/layout.; GVN runs on possibly generic MIR; syntactic metadata comparison alone can miss valid normalization cases.
Test strategy: Use `tests/mir-opt/gvn.rs` MIR-dump tests with `//@ test-mir-pass: GVN`. Cover `manual_slice_mut_len` expecting `_0 = PtrMetadata(_1)`, `array_len` expecting `const 42_usize`, and generic cast metadata pairs: metadata `usize -> ()` and tail `A` vs `B` must not optimize; matching metadata/tail must optimize. Add pointer comparison checks: same-source matching-metadata casts become `Eq([[P2]], [[P3]])`, while `*mut u8` vs `*mut u32` stays `Eq([[M1]], [[M2]])` and fat-to-thin stays `Eq([[M3]], [[M4]])`. Add transmute checks for thin versus fat cases. Also retarget array-length tests to GVN and check `Len`/`PtrMetadata` forms. These are MIR expectations, not runtime equivalence claims.
Cases: 126541-55d13379ac57227a08ba537316adcf2d3c388f57, 126844-dd545e148c0c1680be1555efcb02ece0a16ee3ef
Source: https://github.com/rust-lang/rust/pull/126541
Source: https://github.com/rust-lang/rust/pull/126844
> It's critical that this not eliminate cases like
> which remove metadata.
> ptr_metadata_ty_or_tail(self.tcx, |t| t)
> We have an unsizing cast, which assigns the length to fat pointer metadata.
> // PtrToPtr-then-PtrToPtr can skip the intermediate step
> // PtrToPtr-then-Transmute can just transmute the original, so long as the
> // CHECK: Eq([[M1]], [[M2]])
> && lhs_from == rhs_from
> && self.pointers_have_same_metadata(*lhs_from, lhs_ty)

### Fold Len from place type and only proven reborrow/unsize cases
`Rvalue::Len(place)` may be folded to a static length only from the place type or from tracked wide-pointer metadata with strict shape guards. GVN records a symbolic `Value::Len`; it may fold arrays, simple `[Deref]` reborrows, and array-to-slice unsizing casts, and otherwise must retain the symbolic `Len`. A slice's length is not generally the source array length because subslicing and runtime slice creation change it.
Preconditions: The place type is exactly `ty::Array` or `ty::Slice`; the Validator enforces `ty::Array(..) | ty::Slice(..)`.; For arrays, the length const evaluates to a target `usize`.; DataflowConstProp may use tracked length only when the projection is exactly `[ProjectionElem::Deref]`; any other projection yields top.; GVN may cross a reborrow only while the value is `Value::Address { place: borrowed, .. }` with `[PlaceElem::Deref]`, and may fold an unsize only for `PointerCoercion::Unsize` from array to slice.; KnownPanicsLint may use immediate/aggregate lengths but must return `None` for `Value::Uninit`.
Pitfalls: Do not treat a slice's length as the source array's length when a subslice or runtime slice creation is involved.; Do not treat `Len` and `PtrMetadata` as interchangeable for optimization: one consumes a place, the other a pointer value.; Do not drop projection/type guards; GVN must fall back to a symbolic `Value::Len` and DataflowConstProp to top when the place shape is not understood.; Do not assume a length for partially initialized or unknown aggregates.; Do not emit `PtrMetadata` in pre-runtime MIR; the Validator rejects it outside runtime MIR.
Test strategy: Use MIR-opt tests for `DataflowConstProp` and GVN with `EMIT_MIR_FOR_EACH_PANIC_STRATEGY` and bit-width revisions. Assert `CHECK-NOT: {{_.*}} = Len(`, `CHECK-NOT: assert(move _`, and a constant length for direct fixed-array/unsize cases. Pair a direct fixed array or unsize case expecting a constant with a slice parameter or subslice case expecting symbolic `Len`. Force exact rvalues with custom MIR `let c = Len(x);`. These are MIR-dump checks, not execution claims.
Cases: 135709-c69dea90d70212bb430f183df62edc09c8c8a89f
Source: https://github.com/rust-lang/rust/pull/135709
> Temporarily bring back `Rvalue::Len`
> +            Rvalue::Len(place) => {
> +                } else if let [ProjectionElem::Deref] = place.projection[..] {
> +                    state.get_len(place.local.into(), &self.map)
> +                    FlatSet::Top
> +        // Reborrowing copies length information from one pointer to the other.
> && let [PlaceElem::Deref] = borrowed.projection[..]
> +        // We have an unsizing cast, which assigns the length to wide pointer metadata.
> && let CastKind::PointerCoercion(ty::adjustment::PointerCoercion::Unsize, _) = kind
> +        // Fallback: a symbolic `Len`.

### Aggregate-to-copy needs field/variant/type guards, stable LHS projections, and no new aliasing reads
GVN's `simplify_aggregate_to_copy` may replace an aggregate construction whose fields are one-to-one `Field(i)` projections of one common base place with `Rvalue::Use(Operand::Copy(base_place))`, but only after checking same nominal type, matching field indices, matching enum variant, an unmutated base, and a reconstructible place. The LHS rewrite is allowed for stable-offset projections but not for complex projections that could make `*a = copy (*b)` overlap or alias. Historically the unguarded rewrite was marked unsound because it introduced new dereferences without checking aliasing, and was gated behind `-Zunsound-mir-opts`; the reusable invariant is that replacing aggregate construction with a later re-read is valid only if intervening writes cannot change the source place.
Preconditions: All fields correspond one-to-one to the same aggregate value: `copy_from_value == pointer` and `from_index.index() == index`.; The reconstructed copy source is available from a local via `try_as_local`, and the rvalue type equals the reconstructed place type.; For enums, a source `Downcast(_, read_variant)` either matches the aggregate's `variant_index` (and is stripped) or the rewrite is rejected.; Any local consumed by the new copy, including `Index` locals, is added to `reused_locals` so `StorageLive`/`StorageDead` are removed.; For LHS rewriting, `allow_complex_projection` is `lhs.projection[..].iter().all(PlaceElem::is_stable_offset)`.
Pitfalls: Do not collapse aggregates merely because fields look like projections of one base; different nominal types, swapped fields, mutated bases, and mismatched enum variants must block the rewrite.; Do not allow complex LHS projections unconditionally; doing so can create `*a = copy (*b)` where source and destination may alias and the assignment overlaps.; Do not create assignments between different fields of the same local.; Copying an existing aggregate value is not equivalent to constructing the aggregate when the source place can be mutated through an alias before use.; The old code could return `Some(value)` even when it did not rewrite the rvalue; 'recognized as copyable' is not the same as 'rvalue was actually rewritten'.; The historical fix did not revert the implementation; it marked the optimization unsound and gated tests with `-Zunsound-mir-opts`.
Test strategy: Use `tests/mir-opt` GVN tests with `CHECK`/`CHECK-NOT` and `EMIT_MIR` diffs. Positive case: `_0 = copy (*_1);` for a one-to-one same-type aggregate. Negative cases: different nominal type, swapped field indices (`SameType { a: v.b, b: v.a }` must not become `copy v`), mutated base, same/different enum variant, and `StorageDead`/`Index` cases. For LHS projections, check stable `_1.0` can become `(_1.0) = copy (*_4);` while an overlapping deref case must not gain a copy assignment. Add a `run-pass` regression with `release` (`-C opt-level=1`) and `debug` (`-C opt-level=0`) revisions asserting the original `Some(col)` is preserved. Gate any historical unsound expectation with `-Zunsound-mir-opts`. These are focused regression expectations, not universal proof.
Cases: 128299-25d434b254bf45347210095600c0a47f65bcaa54, 146289-52f74a5162e20e6b9bc8a94f61009fd9d4f38fdb, 132356-cfb4c05d77df4a6bcc53924eddb3a35102b65da9, 132468-0f95b22c12bf01116622ffff58573a3220bd5528
Source: https://github.com/rust-lang/rust/pull/128299
Source: https://github.com/rust-lang/rust/pull/146289
Source: https://github.com/rust-lang/rust/pull/132356
Source: https://github.com/rust-lang/rust/pull/132468
> All fields must correspond one-to-one and come from the same aggregate value.
> copy_from_value == pointer
> from_index.index() == index
> // The copied variant must be identical.
> if rvalue.ty(self.local_decls, tcx) == place.ty(self.local_decls, tcx).ty {
> GVN: Allow reusing aggregates if LHS is not a simple local.
> // FIXME: This also avoids any kind of projection, not just derefs. We can add allowed projections.
> Avoid creating `*a = copy (*b)`, as they might be aliases resulting in overlapping assignments.
> /// Check that we do not create overlapping assignments.
> (_1.0: Adt) = copy (*_4);
> Mark `simplify_aggregate_to_copy` mir-opt as unsound
> introduce[d] new dereferences without checking for aliasing
> -         _0 = Option::<i32>::Some(move _9);
> +         _0 = copy (*_2);
> // unsound: https://github.com/rust-lang/rust/issues/132353
> (*_1) = const Option::<i32>::None;

### Invalidate cached derefs on non-local writes, unsafe terminators, and loop headers
GVN caches dereferenced values and may reuse them, but the cache must be invalidated when an aliasing non-local mutation can occur. The historical pre-pass computed SSA values through `for_each_assignment_mut`, which skips side-effecting statements such as dereference assignments, so a value derived from `*r` could be reused after `*v = ...` through an alias. The corrected pass computes values on the fly in reverse postorder, tracks interned derefs, and turns them opaque when a mutating place use has a non-empty projection or when a non-trivial terminator is reached. Separately, reverse postorder is not topological in the presence of loops, so GVN must invalidate derefs at loop headers before processing them.
Preconditions: GVN runs and has cached a dereference such as `*r` through an immutable or shared reference.; A mutating use of a place with a non-empty projection occurs, or a terminator other than `SwitchInt`/`Goto` is reached, or a loop header is visited.; For the shared-borrow case, the historical reuse condition was a `Mutability::Not` reference with a `Freeze` pointee; that reuse was marked unsound and gated behind `unsound_mir_opts`.; For loops, the CFG contains a back edge or loop header, including self-loops, and the loop body contains an indirect write that may alias the cached deref.
Pitfalls: Do not conflate `T: Freeze` with stability of the storage holding a shared reference; the reference itself may be mutated through unsafe aliasing.; Do not treat every deref reuse as wrong: derefs can still be reused inside uninterrupted regions.; Only `SwitchInt` and `Goto` are safe terminators for preserving derefs; calls and ASM must invalidate.; Do not assume reverse postorder is topological once loops exist; a not-yet-processed loop-body statement or terminator may have performed an indirect write.; For loop headers, invalidate before visiting the header's data, and mark a block visited only after checking successors so self-loops are handled.; The negative directive in the historical loop test is misspelled `// CEHCK-NOT: copy (*[[VAL_REF]]);`; a focused test should spell it correctly or the negative assertion will silently not run.
Test strategy: Use the miscompile reproducer: read `Some(col)` through an aliasing reference, overwrite `*v = None`, then return `Some(col)`. MIR checks should see `(*[[v]]) = const Option::<i32>::None;`, then `CHECK-NOT: _0 = copy (*[[v_alias_2]])`, then `_0 = Option::<i32>::Some`. Add a custom-MIR `SetDiscriminant` variation and assert GVN performs no stale-deref substitution. For loops, add a GVN MIR test and a `-O` `run-pass` test: capture a value before a loop, mutate through an aliasing reference inside the loop, and assert the returned value is still the pre-write variant, with `CHECK-NOT: copy (*[[VAL_REF]])`. Re-run clone-to-copy tests without `-Zunsound-mir-opts` to confirm clone-to-copy still fires. These are focused expectations, not proof of universal equivalence.
Cases: 132527-7d44887374ee667bd5aeb5e861032b8ce4093b29, 133474-906f66fb4c22daa8a6f97e5c048e9f6ab3fd9051, 147607-2048b9c027c8c55d1a83be5d769bb65a855397d3, 147791-408e09e77c9feaa6872671b3505416b357ddff02
Source: https://github.com/rust-lang/rust/pull/132527
Source: https://github.com/rust-lang/rust/pull/133474
Source: https://github.com/rust-lang/rust/pull/147607
Source: https://github.com/rust-lang/rust/pull/147791
> Because the `for_each_assignment_mut` traversal skips statements which have side effects, such as dereference assignments, the computation may be unsound.
> // Non-local mutation maybe invalidate deref.
> if context.is_mutating_use() && !place.projection.is_empty() {
> // unsound: https://github.com/rust-lang/rust/issues/130853
> && let Some(Mutability::Not) = ty.ref_mutability()
> && pointee_ty.is_freeze(self.tcx, self.typing_env())
> // CHECK-NOT: _0 = const true;
> // N.B. With loops, reverse postorder cannot produce a valid topological order.
> state.invalidate_derefs();
> A statement or terminator from inside the loop, that is not processed yet, may have performed an indirect write.
> // CEHCK-NOT: copy (*[[VAL_REF]]);

### Index projections must use the index value, bail out on non-SSA indices, and avoid flattening derefs through Index
GVN's projection handling must respect the value of a dynamic index at the point the place or address was formed. A repeated-array index projection may not continue simplification when the index local is non-SSA and the value cannot be converted to a local, because a later overwrite of that local would change which element is accessed. Address projections must carry the index's `VnIndex` value, not the raw local/place, so later overwrites cannot reinterpret the address. Deref flattening must not `project_deeper` through a pointee projection containing `ProjectionElem::Index`, because the index local may not hold the same value at the current location as when the pointee was borrowed.
Preconditions: GVN processes a `Value::Repeat` indexed projection, an address/borrow with an `Index` projection, or a deref place whose resolved pointee projection contains `Index`.; The index local is non-SSA or otherwise may change after the place/address is formed.; For address projections, the representation uses `ProjectionElem<VnIndex, Ty<'tcx>>` and separates the base (`AddressBase::Local` or `AddressBase::Deref`) from the remaining projection; address projections do not contain `Deref`.; For repeated indices, `*from_non_ssa_index |= self.locals[idx].is_none();` records the hazard and simplification bails out if a local cannot be recovered.
Pitfalls: Do not equate an `Index` projection's local-place identity with the index value; the local may be overwritten after the borrow is formed.; Do not blanket-disable all repeat-index simplification; the local case may still optimize to a repeated local while the place case retains the dereference.; An SSA/non-SSA guard alone is insufficient if the address still stores a raw place rather than the index's `VnIndex`.; Being an SSA local does not guarantee its value at an arbitrary later location matches its value where the pointee was borrowed.; Flattening through `ProjectionElem::Index` can create places referring to non-existing locals or use stale index values.
Test strategy: Add custom-MIR GVN tests with `EMIT_MIR` for both repeated-place (`array = [*val; 5]`) and repeated-local (`array = [val; 5]`) cases, overwriting `idx1 = idx2` between `elem = &array[idx1]` and `RET = *elem`. The place case should retain the original dereference (`_0 = copy (*_5)`), while the local case may simplify to `_0 = copy _3`. For address projections, use distinct array elements so a stale index is observable and check the dereference remains anchored to the old index value, not the overwritten local. For deref flattening, add a `dereference_indexing(array: [u8; 2], index: usize)` test requiring `[[i]] = Add(copy _2, const 1_usize);` and `[[a]] = &_1[[[i]]];`, with `CHECK-NOT` preventing a later indexed temporary. These are MIR expectations plus focused executable assertions where supplied.
Cases: 141252-be5d6c5425e8dfdf1662225fb23d6deb0e124dd4, 144477-3d96e54656927e4870b7b4aaa0afa099e1fc012a, 145030-ebd60b9b8fb1dd1aaac5e1b705d1852f7bc6869b
Source: https://github.com/rust-lang/rust/pull/141252
Source: https://github.com/rust-lang/rust/pull/144477
Source: https://github.com/rust-lang/rust/pull/145030
> *from_non_ssa_index |= self.locals[idx].is_none();
> If access to non-SSA locals is unavoidable, bail out.
> We cannot transform `*elem` to `array[idx1]` in the following code, as `idx1` has already been modified.
> GVN: Use a VnIndex in Address projection.
> Indexing semantically relies on the index' value, but the implementation uses the index' place.
> This PR fixes that by using `ProjectionElem<VnIndex, Ty<'tcx>>` instead of the raw `PlaceElem<'tcx>`.
> GVN:  Do not flatten derefs with ProjectionElem::Index.
> // That local is SSA, but we otherwise have no guarantee on that local's value at
> // the current location compared to its value where `pointee` was borrowed.
> if pointee.projection.iter().all(|elem| !matches!(elem, ProjectionElem::Index(_))) {

### Place reconstruction must not append projections after a terminal Deref
GVN's `try_as_place` reconstructs a MIR place from a value graph. If the accumulated projection already ends in `PlaceElem::Deref` and no local has been recovered, trying to append further projections produces an ill-formed place because `Deref` can only be the first projection in a place. The corrected behavior returns `None` instead of extending the projection.
Preconditions: GVN runs `try_as_place` on a value index.; The accumulated projection already ends with `PlaceElem::Deref`.; No local has been recovered for the place.; Without the guard, control would fall through to the `Value::Projection` extension branch.
Pitfalls: Do not treat `Deref` as an ordinary projection that can be freely followed by additional projections during reconstruction.; Returning `Some(place)` with projections after `Deref` yields an ill-formed place even if the value graph otherwise type-checks.; The supplied patch contains only the compiler change and no regression-test hunk; do not infer a test from it.
Test strategy: Construct a focused GVN place-reconstruction scenario where the accumulated projection is `[Field(1), Deref]`, no local is found, and a further `Value::Projection` would otherwise be appended. The corrected behavior is `None`; the historical behavior would return a place with projections after `Deref`. No compiler was built or executed for this analysis.
Cases: 146298-91241a1d255bde9d1bc3399c1c1f779bb17f1cfa
Source: https://github.com/rust-lang/rust/pull/146298
> GVN: Ensure indirect is first projection in try_as_place.
> } else if projection.last() == Some(&PlaceElem::Deref) {
> // `Deref` can only be the first projection in a place.
> // Trying to add projections will only result in an ill-formed place.
> return None;

### GVN relies on inherited-impossible bodies being marked unreachable before layout evaluation
This is a cross-pass precondition for GVN's layout-dependent folding: a body whose enclosing item has an impossible inherited where-clause must be cleared to unreachable before later MIR optimization or const eval evaluates layouts. The historical `ImpossiblePredicates` computation used only the body def's own global predicates, so derived impls, closures, and nested items under an impossible ancestor bound stayed reachable. GVN/const-prop then processed values with uncomputable layouts and hit ICEs such as ScalarPair versus Scalar. The corrected predicate selection uses the instantiated identity predicate set, filters error-carrying and unevaluated-const-projection clauses, and clears the body when predicates reference errors or are impossible. GVN itself does not compute these predicates; it assumes the body is already unreachable when layouts are not computable.
Preconditions: The impossible/trivial bound is inherited from a parent item rather than present directly on the body's own DefId.; A later MIR pass or const-eval performs work on the body, including GVN, inlining, const propagation, or promotion.; The body contains a value whose layout or const evaluation depends on the unsatisfiable predicate, such as `Option<str>`, an associated const/type, or a promoted closure allocation.; For error-bound cases the predicate references an error type; for const cases the clause may contain an unevaluated const projection.
Pitfalls: Using only `predicates_of(...).predicates` omits parent predicates; for this precondition the pass must use the instantiated identity predicate set.; Do not feed clauses with unevaluated const projections into the impossibility check; the source says they cause cycles.; Error-referencing predicates must short-circuit before const evaluation.; Clearing the body intentionally degrades diagnostics to `error[E0080]: entering unreachable code`; that message change is not a GVN correctness regression.; Moving crash repros to UI tests with `//@ build-pass` is part of the coverage; an old test expecting the old ICE message will not verify the unreachable marking.
Test strategy: Add UI regressions where the impossible bound lives on a parent item and a descendant/derived body performs const work. Use inherited trivial bounds under `where str: Sized` or `where for<T> T: Copy`, compile with GVN/Inline enabled and `//@ build-pass`; for error bounds use `fn a() where b: Sized` and `fn f() -> &'static str where Self: Sized` with `-C opt-level=1 -Zvalidate-mir` and expect normal name-resolution errors but no ICE. Companion tests should assert `error[E0080]: entering unreachable code` plus the note `evaluation of ... failed here` for cases such as `[(); { let _a: Option<str> = None; 0 }]`. No compiler was built or executed for this analysis.
Cases: 144233-b1d88ba086ee6f34584ed4e8eb09761a03fe249d
Source: https://github.com/rust-lang/rust/pull/144233
> Consider parent predicates in ImpossiblePredicates pass.
> let predicates = tcx.predicates_of(body.source.def_id()).instantiate_identity(tcx);
> // Clauses that refer to unevaluated constants as they cause cycles.
> if predicates.references_error() || traits::impossible_predicates(tcx, predicates) {
> error[E0080]: entering unreachable code
> Got a scalar pair where a scalar was expected

### offset_of lowering no longer reaches GVN as NullOp::OffsetOf
`offset_of!` lowering changed from a dedicated `Rvalue::NullaryOp(NullOp::OffsetOf(fields), ty)` to a const block summing calls to a new `offset_of::<T>(variant: u32, field: u32)` intrinsic. GVN must stop handling a dedicated OffsetOf NullOp and instead leave the const block for evaluation: it may fold to a concrete `usize` when the container is concrete, but generic containers remain opaque because layout depends on `T`. Nested field paths are a sum of per-hop intrinsic calls, not one flattened offset.
Preconditions: The expression originates from `std::mem::offset_of!`, which now expands to a const block and is desugared at THIR-building time.; The new intrinsic is declared `pub const fn offset_of<T: PointeeSized>(variant: u32, field: u32) -> usize` with `#[lang = "offset_of"]` and `#[rustc_intrinsic_const_stable_indirect]`.; `Rvalue::NullaryOp` carries only `NullOp::RuntimeChecks` and has no separate type operand.; For folding to a constant, the const block's container types must be concrete enough for layout evaluation.
Pitfalls: Nested paths are a sum of per-hop calls; folding only the first call is wrong. For `offset_of!(Alpha, z.0)`, expect `offset_of::<Alpha>(...)` plus `offset_of::<Beta>(...)` and an `AddWithOverflow`.; Do not fold a generic const block such as `const generic::<T>::{constant#0}` to a concrete offset.; `Rvalue::NullaryOp` no longer carries a `Ty`; visitors and type checkers that previously visited a nullary operand type must stop doing so.; The new `offset_of` intrinsic is only for const evaluation; LLVM codegen refuses to generate code for it, and it is wrapped in a const block.; Const checking only honors `span.allows_unstable` when the callee is const-stable; do not bypass recursive stability.
Test strategy: Use MIR dump tests. At `-Zmir-opt-level=0`, check generated const bodies such as `_0 = offset_of::<Alpha>(const 0_u32, const 0_u32)`, enum `_0 = offset_of::<Blah>(const 1_u32, const 1_u32)`, and nested `AddWithOverflow` for `z.0`/`z.1`. Use `//@ test-mir-pass: GVN` diffs: concrete `const concrete::{constant#0}` may become `_1 = const 4_usize`, while `const generic::<T>::{constant#0}` stays unfolded. Add UI tests for `offset_of!` inside array lengths and unsized tails. These are MIR expectations, not codegen or execution proof.
Cases: 148151-e7991602edc786052e94e00777518cd5093209e4
Source: https://github.com/rust-lang/rust/pull/148151
> Replace OffsetOf by an actual sum of calls to intrinsic.
> This PR proposes to replace it by an inline constant which sums calls to a new intrinsic `offset_of(variant index, field index)`.
> NullOp::OffsetOf(fields) => self
> ImmTy::from_uint(val, ty).into()
> _1 = const concrete::{constant#0};
> _1 = const 4_usize;
> _1 = const generic::<T>::{constant#0};
> // CHECK: [[z:_.*]] = offset_of::<Alpha>(const 0_u32, const 2_u32)

### Function reification casts are opaque and must not be merged
`PointerCoercion::ReifyFnPointer` now carries target `Safety`, and GVN must treat every reification cast as a fresh opaque value. Two reifications of a generic function or closure may have identical target pointer types but represent different function instances; common-numbering them would call the wrong function. Match `ReifyFnPointer(_) | ClosureFnPointer(_)` regardless of safety payload, and keep each cast distinct.
Preconditions: MIR contains `Rvalue::Cast(CastKind::PointerCoercion(PointerCoercion::ReifyFnPointer(_) | PointerCoercion::ClosureFnPointer(_), _), operand, to_ty)`.; Sources include function items and non-capturing closures; targets include safe and unsafe function-pointer types.; Multiple reifications of a generic function or closure may appear.; MentionedItems and the Validator visit the cast; MentionedItems must still collect the reified item, and validation must account for target safety.
Pitfalls: Do not merge reifications in GVN merely because their target types look identical; each reification of a generic fn may get a different pointer.; Do not drop `ReifyFnPointer` casts from MentionedItems; they are item mentions.; Do not assume source and target safety are equal; safe fn items may coerce to unsafe fn pointers, but unsafe fn items may not coerce to safe fn pointers.; Do not match only one safety payload; match `ReifyFnPointer(_)` so both safe and unsafe reifications are handled.; Do not attribute the separate HIR coercion inference-variable leak to GVN; its regression test exercises HIR coercion.
Test strategy: Use `tests/mir-opt/gvn.fn_pointers.rs` with two `identity::<u8> as fn(u8) -> u8` reifications and inspect the GVN dump to confirm both casts remain and print as `PointerCoercion(ReifyFnPointer(Safe), AsCast)`. Use const-prop formatting tests for cast display. For safety, use a UI LUB test where safe/unsafe fn defs in an `if` must LUB to an unsafe fn pointer, including target-feature-aware cases, and a leak-checking test that forces an FnDef LUB to `fn()`. Add an unsafe-target reification case expecting `ReifyFnPointer(Unsafe)` when constructing the variant directly. These are source/dump expectations, not execution claims.
Cases: 148602-2f95ecfdd63c2ec27067d0cf3e8eb1155b872af7
Source: https://github.com/rust-lang/rust/pull/148602
> if let CastKind::PointerCoercion(ReifyFnPointer(_) | ClosureFnPointer(_), _) = kind {
> // Each reification of a generic fn may get a different pointer.
> // Do not try to merge them.
> _1 = identity::<u8> as fn(u8) -> u8 (PointerCoercion(ReifyFnPointer(Safe), AsCast));
> _4 = identity::<u8> as fn(u8) -> u8 (PointerCoercion(ReifyFnPointer(Safe), AsCast));
> ReifyFnPointer(hir::Safety),
> if src_sig.safety().is_safe() && target_safety.is_unsafe() {
