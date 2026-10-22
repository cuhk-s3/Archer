# CheckUnnecessaryTransmutes
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Do not call `expect`, `unwrap`, or assert success on `span_to_snippet` in this lint path; `SourceNotAvailable` is an expected runtime possibility.
- Do not emit `UNNECESSARY_TRANSMUTES` merely because the snippet is missing: the correct action is to skip the lint.
- Do not suppress or alter the normal lint analysis when the snippet is available; preserve `is_unnecessary_transmute` behavior and diagnostics in that case.
- Do not move the panic to another unwrap or assertion on the same snippet-retrieval path.
- A regression test for this condition should require successful compilation/no ICE, not a lint diagnostic, because skipping is the expected outcome.
- Do not treat value agreement on {0,1} as full semantic equivalence; the historical rewrite erased the validity assumption and changed behavior for values such as 2 and 255.
- Do not suggest `_ == 1`, `_ != 0`, or `_ % 2 == 0` as replacements; each would remove that assumption.
- Do not generalize the removed arm to signed integer sources: `transmute(1i8)` was already not linted by this pass and remains a clippy matter.
- Do not use a verbose match with `unreachable_unchecked` as a practical lint suggestion; the historical discussion explicitly calls that form very verbose.
- When updating diagnostics, remove the u8-to-bool expectation rather than restoring `help: replace this with: `(1u8 == 1)``; the supplied UI evidence changes the total from `error: aborting due to 36 previous errors` to `error: aborting due to 35 previous errors`.

## Patterns Not Well Handled

### Skip optional transmute lint when argument source snippet is unavailable
CheckUnnecessaryTransmutes must treat inability to retrieve a transmute argument's source text as a reason to skip the optional lint, not as an internal invariant. The historical implementation called `self.tcx.sess.source_map().span_to_snippet(arg).expect("ok")`; when the span came from a remapped auxiliary-crate macro, retrieval produced `Err(SourceNotAvailable { ... })` and the lint pass panicked during MIR processing. The correction guards with `&& let Ok(snippet) = self.tcx.sess.source_map().span_to_snippet(arg)` and only invokes `is_unnecessary_transmute` when a snippet exists. This changes failure handling only: when source text is available, the existing unnecessary-transmute analysis and diagnostic behavior should remain unchanged. The supplied validation modeled the pre-fix result as a panic (code 2) and the corrected result as a deliberate false/skip (code 0) for the unavailable-snippet input, while both versions took the same lint path for an available snippet.
Preconditions: The MIR terminator is a call to the transmute intrinsic, detected through the intrinsic definition, before the snippet is requested.; The argument span's source is unavailable to the source map, e.g. a remapped external or auxiliary-crate macro span.; Source availability is not known statically; snippet retrieval can legitimately return `Err(SourceNotAvailable)` during linting.
Pitfalls: Do not call `expect`, `unwrap`, or assert success on `span_to_snippet` in this lint path; `SourceNotAvailable` is an expected runtime possibility.; Do not emit `UNNECESSARY_TRANSMUTES` merely because the snippet is missing: the correct action is to skip the lint.; Do not suppress or alter the normal lint analysis when the snippet is available; preserve `is_unnecessary_transmute` behavior and diagnostics in that case.; Do not move the panic to another unwrap or assertion on the same snippet-retrieval path.; A regression test for this condition should require successful compilation/no ICE, not a lint diagnostic, because skipping is the expected outcome.
Test strategy: Use a UI check-pass test whose auxiliary crate exports a macro expanding to a transmute, compile that auxiliary crate with `--remap-path-prefix=/=/non-existent`, and call the macro from the main test. The supplied reproducer uses an auxiliary macro around `std::mem::transmute(e)` and marks the main test `//@ check-pass`. Complement with a same-source or non-remapped case where the snippet is available, verifying that legitimate unnecessary-transmute linting remains active. The submitted pair covered both unavailable and available snippets; this is focused evidence, not universal proof of equivalence.
Cases: 140284-d3a4ebca85fd6ec24793794fefdb3b4021526e1d
Source: https://github.com/rust-lang/rust/pull/140284
> self.tcx.sess.source_map().span_to_snippet(arg).expect("ok")
> && let Ok(snippet) = self.tcx.sess.source_map().span_to_snippet(arg)
> && let Some(lint) = self.is_unnecessary_transmute(func, snippet, span)
> removes expect() from #136083 and fixes #140277
> ok: SourceNotAvailable { filename: Real(Remapped { local_path: None, virtual_name:
> //@ compile-flags: --remap-path-prefix=/=/non-existent
> //@ check-pass

### Do not rewrite u8-to-bool transmute to a comparison: preserve the implicit validity assumption
CheckUnnecessaryTransmutes historically proposed replacing `transmute::<u8, bool>(x)` with `(x == 1)` via `(Uint(_), Bool) => err(format!("({arg} == 1)")),`. That rewrite is not semantics-preserving because the transmute carries an implicit validity precondition: the historical note states `transmute::<u8, bool>(x)` will codegen to an `assume(u8 < 2)`; and `_ == 1` or `_ != 0` or `_ % 2 == 0` would remove that assumption. The comparison accepts every u8 and returns false for out-of-range bytes, whereas the original transmute assumes the byte is 0 or 1. The lint removed the unsigned-integer-to-bool arm and intentionally leaves this case to clippy, documented by `We chose not to lint u8 -> bool transmutes, see #140431`. The change removes an unsound lint suggestion; it does not alter the validity rule for actual transmute code.
Preconditions: The candidate expression is a transmute whose source is an unsigned integer and whose destination is bool.; The original transmute has an implicit validity assumption such as `assume(u8 < 2)`; any replacement suggestion must preserve that precondition.; Agreement on in-domain bool representations 0 and 1 is insufficient to justify a rewrite, because the replacement must not widen the accepted input domain.
Pitfalls: Do not treat value agreement on {0,1} as full semantic equivalence; the historical rewrite erased the validity assumption and changed behavior for values such as 2 and 255.; Do not suggest `_ == 1`, `_ != 0`, or `_ % 2 == 0` as replacements; each would remove that assumption.; Do not generalize the removed arm to signed integer sources: `transmute(1i8)` was already not linted by this pass and remains a clippy matter.; Do not use a verbose match with `unreachable_unchecked` as a practical lint suggestion; the historical discussion explicitly calls that form very verbose.; When updating diagnostics, remove the u8-to-bool expectation rather than restoring `help: replace this with: `(1u8 == 1)``; the supplied UI evidence changes the total from `error: aborting due to 36 previous errors` to `error: aborting due to 35 previous errors`.
Test strategy: Exercise the UI test containing `let z: bool = transmute(1u8);` and verify it no longer receives an `unnecessary transmute` diagnostic, while adjacent linted forms such as `let z: u8 = transmute(z);` and `let z: i8 = transmute(z);` still do. The supplied semantic pair used inputs 0u8, 1u8, 2u8, and 255u8: both original and rewrite agree on 0 and 1, but the original has no defined bool for 2 and 255 (modeled as code 2) while `(x == 1)` returns false (code 0). Treat the `assume(u8 < 2)` behavior as a precondition rather than claiming it was executed, and use this differential test as targeted evidence for the domain mismatch, not as universal proof.
Cases: 140431-de8e8641ae8194009b13dcca997e1eaa991b2888
Source: https://github.com/rust-lang/rust/pull/140431
> We chose not to lint u8 -> bool transmutes, see #140431
> (Uint(_), Bool) => err(format!("({arg} == 1)")),
> removes `transmute(u8) -> bool` suggestion due to ambiguity, leave it for clippy
> `transmute::<u8, bool>(x)` will codegen to an `assume(u8 < 2)`;
> `_ == 1` or `_ != 0` or `_ % 2 == 0` would remove that assumption
> `match _ { x @ (0 | 1) => x == 1, _ => std::hint::unreachable_unchecked() }` is very verbose
> let z: bool = transmute(1u8);
> let z: bool = transmute(1i8);
> let z: u8 = transmute(z);
> help: replace this with: `(1u8 == 1)`
> error: aborting due to 36 previous errors
> error: aborting due to 35 previous errors
