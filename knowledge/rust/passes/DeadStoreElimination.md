# DeadStoreElimination
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not delete the marker statement merely because it has no runtime effect; the consumer may still require it.
- Do not delete the marked local without also deleting or rewriting the marker, and do not delete the marker without accounting for its consumer.
- When remapping locals, update the marker's `place.local`; otherwise a stale local index remains after renumbering.
- Do not classify the marker as a real drop or control-flow terminator in liveness/use analysis.
- Do not transfer the supplied lint's consumed/moved/parameter/closure-capture behavior into DeadStoreElimination; keep the DSE invariant limited to preserving and remapping marker references.
- Do not let the validator treat the marker as unsupported or as an executable drop/terminator.
- Do not assume the marker has runtime effects; it must be a no-op for codegen and the other listed consumers.
- For the downstream lint consumer, do not count `Drop` terminators that drop elaboration may later remove; consult `MaybeInitializedPlaces` before the primary effect.
- For the downstream observer set, exclude `_0`, the closure capture-struct local, descendants of BID places, and types with no significant destructor.
- Do not claim the finite supplied cases prove general compiler correctness; they are concrete regression scenarios.

## Patterns Not Well Handled

### Dead-local elimination must count semantic no-op marker statements as Place uses and remap them
When DeadStoreElimination-style cleanup removes or renumbers locals, a `StatementKind::BackwardIncompatibleDropHint { place, reason }` marker is not executable code but still contains a `Box<Place>` reference. It must be counted as a use of its local by used-local collection, and local-index rewriting must update that Place. Otherwise a local that appears unused except for the marker can be deleted or renamed while the marker still references it, leaving invalid MIR. The supplied historical evidence states that this statement is only for MIR linting and is semantically equivalent to `Nop`. The case's HIR tail-expression lint false-positive correction is consumer-side context; it should not be restated as a DeadStoreElimination transformation.
Preconditions: The MIR body contains a `StatementKind::BackwardIncompatibleDropHint { place, reason }` marker.; The marked local may have no ordinary runtime uses, so dead-local or unused-definition analysis could otherwise remove it.; A pass may renumber or rewrite locals while the marker is retained for its lint consumer.; The marker is specified as semantically equivalent to `Nop` and must not be treated as a real drop or terminator.
Pitfalls: Do not delete the marker statement merely because it has no runtime effect; the consumer may still require it.; Do not delete the marked local without also deleting or rewriting the marker, and do not delete the marker without accounting for its consumer.; When remapping locals, update the marker's `place.local`; otherwise a stale local index remains after renumbering.; Do not classify the marker as a real drop or control-flow terminator in liveness/use analysis.; Do not transfer the supplied lint's consumed/moved/parameter/closure-capture behavior into DeadStoreElimination; keep the DSE invariant limited to preserving and remapping marker references.
Test strategy: Construct MIR where a local's only apparent reference is a `BackwardIncompatibleDropHint` marker. Run DeadStoreElimination-style unused-local cleanup and local renumbering, then assert that the local is not removed while the marker remains, or that the marker is rewritten coherently, and that no stale local index remains. Validate the resulting MIR afterward. Concrete tests exercise only the constructed cases and do not by themselves prove universal equivalence.
Cases: 131326-297b618944d4619a1990b1992d9142c6cf893dc6
Source: https://github.com/rust-lang/rust/pull/131326
> +    /// This is semantically equivalent to `Nop`, so codegen and MIRI should interpret this
> +            | StatementKind::Deinit(ref place)
> +            | StatementKind::BackwardIncompatibleDropHint { ref place, reason: _ } => {
> +                PlaceContext::MutatingUse(MutatingUseContext::Store),
> MaybeInitializedPlaces

### Post-elimination MIR with a preserved no-op marker must remain valid and acceptable to all consumers
If dead-store or dead-local elimination preserves a `BackwardIncompatibleDropHint` marker, the resulting MIR must remain valid to the validator and no-op to code generation and other MIR consumers. The historical evidence specifies that the marker is semantically equivalent to `Nop`, so codegen and MIRI should interpret it as such, while validator CFG and type checking must accept the variant instead of rejecting it or falling into an unsupported-statement path. The marker's lint consumer should use `MaybeInitializedPlaces` so only drops actually reachable between the marker and the real drop are considered; this is downstream consumer context, not a DeadStoreElimination behavior. Syntactic over-approximation can incorrectly flag droppy values that are consumed by the return value, moved into a constructor, moved or dropped before the tail expression, are parameters, or are closure captures.
Preconditions: Optimization has preserved or produced a `BackwardIncompatibleDropHint` statement in the MIR body.; MIR validation, codegen, const-eval, borrowck, coverage, coroutine analysis, or dataflow consume the body afterward.; Any lint consumer of the marker runs with move/initialization information available, notably `MaybeInitializedPlaces`.
Pitfalls: Do not let the validator treat the marker as unsupported or as an executable drop/terminator.; Do not assume the marker has runtime effects; it must be a no-op for codegen and the other listed consumers.; For the downstream lint consumer, do not count `Drop` terminators that drop elaboration may later remove; consult `MaybeInitializedPlaces` before the primary effect.; For the downstream observer set, exclude `_0`, the closure capture-struct local, descendants of BID places, and types with no significant destructor.; Do not claim the finite supplied cases prove general compiler correctness; they are concrete regression scenarios.
Test strategy: Run DeadStoreElimination-style cleanup followed by MIR validation on bodies containing the marker, checking that the marker and any required local remain coherent. Add consumer-level checks that codegen and const-eval treat the marker as a no-op, and that the lint consumer does not report consumed, moved, parameter, or closure-capture values while still reporting genuinely reordered transient drops. Use maybe-initialized reachability assertions for the latter and keep edition gating tests for when the lint must not fire.
Cases: 131326-297b618944d4619a1990b1992d9142c6cf893dc6
Source: https://github.com/rust-lang/rust/pull/131326
> +    /// This is semantically equivalent to `Nop`, so codegen and MIRI should interpret this
> +            | StatementKind::BackwardIncompatibleDropHint { .. }
> +fn should_not_lint_when_consumed() -> (LoudDropper, i32) {
> +    // Should not lint because `LoudDropper` is consumed by the return value
> +fn should_not_lint_when_moved() -> i32 {
> +fn should_not_lint_params(x: LoudDropper) -> i32 {
