# InstrumentCoverage
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- ASCII-only tests cannot expose the difference because bytes and code points coincide.
- Blindly adding or subtracting one column can land inside a multi-byte UTF-8 character.
- Resolve line/column before nudging an empty end-of-line span so expansion does not wrap to the next line.
- Column numbers remain 1-based; only their unit changes from code points to bytes.
- Do not fix only individual macro-expansion root causes; a catch-all validation filter is intentional.
- The end_col high bit is reserved for gap regions and must be clear for normal code regions.
- A rejected region triggers debug_assert in debug builds but is otherwise logged/discarded; tests must not assume rejection always panics.
- Do not retain a decision while dropping individual invalid conditions; downgrade all conditions to Branch when the decision is not fully valid.
- Empty spans must be expanded to an adjacent brace before coordinate conversion, or zero-width regions can be emitted.
- Do not expand arbitrary empty spans; expansion over spaces, newlines, or unrelated text can extend past the physical line.
- BytePos(1) adjustment is valid only after confirming the skipped byte is one of the two ASCII braces.
- Guard body-span and source-file boundaries: do not read beyond the source or before byte zero.
- Early MIR enlargement/discard changes dedup/merge and CleanupPostBorrowck dumps; deferring to codegen leaves empty spans until make_coords.
- After body_span storage is removed, use source-file bounds and the first mapping's span for file selection; do not retain stale body-span-based checks.
- Un-enlargeable empty spans must be discarded deliberately, not passed to codegen.
- The test line-number shifts caused by deleting CHECK lines are not coverage semantics.
- Do not emit a covfun record when every mapping was rejected; return None and skip the function.
- Do not merely delete an unused local file table entry when the source-backed fix is to skip the function.
- check_local_file_table must index a bool vector sized to the local file table using each span's file_id.
- Codegen-side debug_assert for empty spans only fires in debug builds; release builds still return None.
- If empty-span enlargement moves earlier, adjacent mappings may merge and functions whose spans cannot be enlarged may disappear from the map.
- The unused-local-file test flag must be paired with an auxiliary crate so llvm-cov does not complain about no coverage metadata.
- Do not inject one increment per BCB association; inject one per unique CounterIncrementSite.
- Do not assume a BCB with incoming edge counters cannot also need its own physical counter; self-loops make the combination legal.
- Only BCB nodes, not edges, can have coverage spans and thus ExpressionUsed statements.
- Do not initialize counters_seen empty and expressions_seen filled in a way that treats per-instance traversal as the sole truth.
- Only direct MappingKind::Code(CovTerm::Expression(id)) mappings require an ExpressionUsed marker; branch/MC/DC expressions may not.
- Unused functions need an explicit !is_used override to force zero mappings.
- Only swap then/else when is_flipped is true, and invert parity for each nested !.
- Do not treat BlockMarker as an ordinary code span or codegen increment.
- Branch mappings have two terms; both must be inserted into the BCB set and handled by map_terms.
- Expansion-generated branch spans are intentionally ignored to reduce macro noise.
- A missing marker-to-block mapping or a marker block outside the coverage graph causes that branch mapping to be dropped.
- if let and let-chains are not instrumented by this implementation.
- Returning empty mappings when the flag is set can make llvm-cov drop the function entirely.
- Do not skip branch or MCDC extraction along with ordinary MIR spans.
- Do not duplicate divergent logic for async and no-mir-spans; one branch can handle both.
- The option parser must accept the new spelling and diagnostics must list it.
- Do not leave all nested conditions attached to depth 0 or reuse the enclosing decision's condition IDs.
- decision_depth must flow through CondBitmapUpdate/TestVectorBitmapUpdate, BcbMappingKind, MCDCBranchSpan/MCDCDecisionSpan, and MIR pretty-printing.
- Push a fresh decision context around the nested decision and pop it afterward; the stack must not become empty.
- A nested decision with only one condition is intentionally left as branch coverage rather than MCDC.
- Do not conflate decision depth with condition ID; nested decisions may reuse condition IDs in separate regions.
- Do not use 0 both as a real condition id and as the no-next-condition sentinel.
- Do not mix old byte sizing with new test-vector bit counts.
- Branch updates use the decision start bitmap_idx, but MCDCDecision uses bitmap_idx + num_test_vectors as the end index.
- The temp variable accumulates cond_index; treating it as a bit position or condition id breaks verification.
- Visit false before true so conditions are touched in the same order as llvm-cov.
- Sort end nodes in descending num_paths order to match LLVM's bitmap-size optimization.
- If the decision span does not contain all condition spans, substitute their joint span.
- Decisions exceeding condition/test-vector limits should emit ordinary branch mappings and warnings.
- Do not use the Coroutine arm for CoroutineClosure; coroutines are never ZST, but an empty-field coroutine-closure aggregate is ZST-like.
- Do not omit CoroutineClosure from def-like aggregate handling.
- Const-prop should bail out on ConstProp of CoroutineClosure values as unsupported.
- Body ABI for a coroutine-closure is Abi::RustCall, not Abi::Rust.
- Coverage must recognize AggregateKind::CoroutineClosure when collecting closure/coroutine aggregate spans.
- Unconditional source_callsite() unexpands too far and loses closure declaration context.
- Use find_ancestor_in_same_ctxt(fn_decl_span) for closure bodies.
- Do not run normal span refinement over the trivial desugared outer async function; keep only the signature span.
- Only add a fake body_span.shrink_to_lo() signature span when the body yielded at least one span.
- Coverage attributes on closures interact with enclosing functions; test both global and local closures.
- Do not treat every expansion like a visible bang macro; split only ExpnKind::Macro(MacroKind::Bang, visible_macro) spans.
- Do not deduplicate non-await, non-macro spans.
- Retain the first await-related or bang-macro covspan per identical span in dominator order.
- The heuristic of picking only the first await-related covspan may be unreliable; test more than a ready future.
- Hiding await's internal Poll branch is a span-refinement change, not a change to async lowering.
- Using ExpnData::parent for tree edges can silently drop macro instrumentation under #[rustfmt::skip] or similar metadata.
- Filter dummy call sites before creating call-site lineage.
- Do not deduplicate await/bang-macro expansions by span alone; select one BCB per child expansion in dominator order.
- BCB selection is kind-dependent: bang macros and await use min_by with dominator order; other expansions use max_by.
- Only truncate bang-macro call-site spans through '!'.
- Use contains, eq_ctxt, and source_equal checks; discard spans outside the body or filling the entire body.
- Do not drop all spans; only spans source-equal to the whole body should be discarded after unexpansion.
- Dropping legitimate nested spans loses coverage.
- Explicit trailing () versus implicit unit return can differ only in coverage rendering, so check both raw mappings and rendered regions.
- Whole-body spans may also arise from macro expansion and closures.
- Closure spans must precede non-closure spans before dedup_by so the closure representative wins.
- Reverse dominator order is required to keep the most-dominated BCB.
- Use span.source_equal, not raw Span equality, so macro-expansion equality is treated correctly.
- dedup_by only removes adjacent equal elements; the preceding sort is an invariant.
- After removing pending_dups, no path remains for special handling of overlapping duplicate spans.
- The mapping count and raw bytes can change (e.g. 7 to 6); update expectations rather than assuming identical output.
- Assuming identical mappings after refiner replacement is wrong; minor loop mapping changes are expected.
- Using the old outer prev.span alone does not reproduce the old cutoff_statements_at behavior; it depended on merged_spans history.
- Do not treat new overlap handling as ordinary interval subtraction; it is BCB-sensitive and discards overlapping different-BCB spans.
- Do not merge solely because spans are adjacent in vectors; final merge requires a.is_mergeable(b), i.e. equal BCBs.
- Do not merge solely on equal BCB: also require a.span.overlaps_or_adjacent(b.span).
- Do not restore fn_sig_span.with_hi(body_span.lo()), which covers the signature-to-body gap.
- More distinct mappings and larger raw metadata are expected after abolishing non-adjacent merges.
- Do not derive holes only from enclosing-function MIR; nested item bodies are separate and cannot be recognized there.
- Do not recurse into a nested item after recording its span, but still visit items inside non-item nested bodies (NestedFilter = All).
- Filter candidate HIR holes by containment and syntax context; unrelated macro-expanded spans must not be carved.
- Merge overlapping or adjacent holes before carving; otherwise fragments can be lost or misordered.
- Split-around-hole implementations must keep both before/after fragments and carry leftovers to later holes; the later discard-on-overlap implementation drops the whole overlapping span instead.
- Re-sort each bucket if the implementation uses buckets; the refiner expects each bucket to be internally sorted.
- Removing MIR hole collection must not break signature-span insertion, which then depends only on non-empty covspans.
- Changing hole spans changes .cov-map layout even where line-level counts look unchanged.
- Checking only codegen_fn_attrs/direct NO_COVERAGE misses inherited attributes.
- Do not treat any ancestor off as unconditional; the nearest attribute wins and an inner on can override.
- Attributes on modules and impl blocks have no direct effect except as inherited defaults.
- Removing NO_COVERAGE requires preserving naked-function exclusion through CodegenFnAttrFlags::NAKED.
- span_delayed_bug does not make malformed code compile; normal validation errors still appear, including E0658 when the feature is disabled.
- The delayed-bug message may appear alongside normal diagnostics; judge success by no internal compiler error/panic.

## Patterns Not Well Handled

### Coverage mappings use 1-based UTF-8 byte columns
InstrumentCoverage must emit coverage-map columns as 1-based byte offsets into the source, because llvm-cov slices source by bytes. Code-point columns mangle non-ASCII source or make llvm-cov fail. Empty spans must be widened by whole UTF-8 character byte widths at character boundaries, not by one code point.
Preconditions: Coverage instrumentation is enabled so code regions are emitted.; A mapped span follows or contains multi-byte UTF-8 text, such as a non-ASCII identifier, string content, or macro-generated code.; llvm-cov consumes the emitted mapping and assumes columns are byte counts.; For empty-span expansion, source text is available and the span lies inside the function body.
Pitfalls: ASCII-only tests cannot expose the difference because bytes and code points coincide.; Blindly adding or subtracting one column can land inside a multi-byte UTF-8 character.; Resolve line/column before nudging an empty end-of-line span so expansion does not wrap to the next line.; Column numbers remain 1-based; only their unit changes from code points to bytes.
Test strategy: Use a coverage UI test with non-ASCII identifiers, string contents, and macro-defined functions. Compare exact .cov-map columns such as the supplied byte-column expectations 20..24 and 25..37, plus an ASCII control that should be unchanged. Do not claim llvm-cov execution; verify mapping expectations.
Cases: 119033-6971e9332d9a7fb1567a6df0f30d03452f505ed3
Source: https://github.com/rust-lang/rust/pull/119033
> coverage: `llvm-cov` expects column numbers to be bytes, not code points
> Normally the compiler emits column numbers as a 1-based number of Unicode code points.
> let nudge_bytes = src.ceil_char_boundary(hi_rpos + 1) - hi_rpos;
> Check that column numbers are denoted in bytes, so that they don't cause

### Validate source regions before emission and keep MCDC decisions atomic
Coverage code regions should be checked before being emitted: coordinates must be nonzero, end_col's high bit must be unset, and (start_line,start_col) must be ordered before or equal to (end_line,end_col). For MCDC, emit an MCDCDecision only when all condition spans and the decision span convert to valid source regions; otherwise downgrade conditions to ordinary Branch mappings rather than filtering conditions independently later.
Preconditions: Coverage instrumentation is enabled for the function.; A CodeRegion/SourceRegion is constructed from a source span, possibly after empty-span expansion and doctest offsetting.; The region can be invalid by ordering, zero coordinate, or high end_col bit.; For MCDC, a decision has multiple condition mappings, and at least one condition or the decision span may fail source-region conversion.
Pitfalls: Do not fix only individual macro-expansion root causes; a catch-all validation filter is intentional.; The end_col high bit is reserved for gap regions and must be clear for normal code regions.; A rejected region triggers debug_assert in debug builds but is otherwise logged/discarded; tests must not assume rejection always panics.; Do not retain a decision while dropping individual invalid conditions; downgrade all conditions to Branch when the decision is not fully valid.; Empty spans must be expanded to an adjacent brace before coordinate conversion, or zero-width regions can be emitted.
Test strategy: Construct cases with well-ordered regions and invalid regions (out-of-order, zero coordinate, high-bit end_col) and inspect whether they are dropped before llvm-cov. For MCDC, compare a decision whose condition spans all convert with one where a condition is invalid: the latter should emit no MCDCDecision and should emit all valid conditions as Branch mappings. Compare exact .cov-map and MIR mapping expectations rather than claiming a runtime reproduction.
Cases: 119460-21e5beae3cc4ffd2adea9ae7b4a9d8b84a4bc0a8, 133608-9461f4296ffcbd75440ec211ead7bff6fb86012c
Source: https://github.com/rust-lang/rust/pull/119460
Source: https://github.com/rust-lang/rust/pull/133608
> If we emit a coverage region that is improperly ordered (end < start), `llvm-cov` will fail with `coveragemap_error::malformed`
> So it makes sense to also have a catch-all check that will prevent improperly-ordered regions from ever being emitted.
> if all_nonzero && end_col_has_high_bit_unset && is_ordered {
> let Some(cov_span) = make_cov_span(span) else { continue };
> if conditions.len() == num_conditions as usize
> Reverting #133418 due to regressions reported at #133606.

### Empty-span repair is brace-only and pipeline-placement-sensitive
Empty coverage spans are poorly handled by llvm-cov, but they must not be enlarged arbitrarily. The source-backed rule is to expand an empty span only over an adjacent ASCII '{' after it or '}' before it, or discard it. The repair must be bounded correctly: early versions used the function body span, later versions removed body_span and used source-file bounds. Moving repair between MIR InstrumentCoverage and LLVM codegen changes merge behavior and downstream MIR observations; multiple source changes show that this placement is a real compatibility hazard, including a revert that restored codegen-side enlargement.
Preconditions: A refined coverage span is empty (lo == hi).; Source text is available from the source map.; The next source byte is ASCII '{' and is within the allowed bounds for forward expansion, or the previous source byte is ASCII '}' and start > 0 for backward expansion.; The function's mappings are assumed to be in one source file; later code anchors file selection on the first mapping or previously on body_span.
Pitfalls: Do not expand arbitrary empty spans; expansion over spaces, newlines, or unrelated text can extend past the physical line.; BytePos(1) adjustment is valid only after confirming the skipped byte is one of the two ASCII braces.; Guard body-span and source-file boundaries: do not read beyond the source or before byte zero.; Early MIR enlargement/discard changes dedup/merge and CleanupPostBorrowck dumps; deferring to codegen leaves empty spans until make_coords.; After body_span storage is removed, use source-file bounds and the first mapping's span for file selection; do not retain stale body-span-based checks.; Un-enlargeable empty spans must be discarded deliberately, not passed to codegen.; The test line-number shifts caused by deleting CHECK lines are not coverage semantics.
Test strategy: Construct paired sources differing only in the byte adjacent to an empty span: empty before '{' versus before newline/space, empty after '}' versus after another character, and empty spans at body/source boundaries. Check MIR InstrumentCoverage and CleanupPostBorrowck dumps for empty versus widened coordinates, and .cov-map merge counts. Include async-closure and match-arm cases; the supplied async-closure expectation changes between two mappings and one mapping depending on repair placement.
Cases: 132675-925dfc8608e1906e0fc51518f9b0cf40f22a5618, 138659-cc8336b6c1c5400cf85521218afda47dbbbe782c, 144298-f877aa7d14916f71a2f88c6d4c009e7ded7684c4, 144480-2b17897092443d3873e273dfa6366784b78f5b44, 144663-2e6f4a59226fd82c526df0f61fefc6fea44e7750
Source: https://github.com/rust-lang/rust/pull/132675
Source: https://github.com/rust-lang/rust/pull/138659
Source: https://github.com/rust-lang/rust/pull/144298
Source: https://github.com/rust-lang/rust/pull/144480
Source: https://github.com/rust-lang/rust/pull/144663
> coverage: Restrict empty-span expansion to only cover `{` and `}`
> if try_next && src.as_bytes()[end] == b'{' {
> let try_next = hi < fn_cov_info.body_span.hi();
> if src.as_bytes().get(end).copied() == Some(b'{') {
> +    // For all empty spans, either enlarge them to be non-empty, or discard them.
> -Number of file 0 mappings: 2
> Revert "coverage: Enlarge empty spans during MIR instrumentation, not codegen"
> let span = ensure_non_empty_span(source_map, span)?;
> coverage: Re-land "Enlarge empty spans during MIR instrumentation"
> debug_assert!(false, "can't make coords from empty span: {span:?}");

### Skip coverage records with no surviving regions or unused local file IDs
When span-to-coordinate conversion is deferred to codegen, some or all spans of a used function can be rejected. The function must be skipped without asserting and without emitting a zero-region record that makes llvm-cov abort. Separately, a function's local file table must not contain a local file ID that has no mapping region; detect unreferenced local file IDs and skip that function's covfun record.
Preconditions: Coverage instrumentation has produced mappings whose spans may be empty, improper, zero-coordinate, high-bit end_col, or otherwise invalid.; Conversion/validation happens at codegen or all spans are forced invalid by a testing-only option.; For the local-file case, the function has a virtual file mapping/local file table and at least one entry may be unreferenced by any coverage span.; The test binary still has some valid coverage metadata, often via an auxiliary instrumented crate, so llvm-cov itself has metadata to consume.
Pitfalls: Do not emit a covfun record when every mapping was rejected; return None and skip the function.; Do not merely delete an unused local file table entry when the source-backed fix is to skip the function.; check_local_file_table must index a bool vector sized to the local file table using each span's file_id.; Codegen-side debug_assert for empty spans only fires in debug builds; release builds still return None.; If empty-span enlargement moves earlier, adjacent mappings may merge and functions whose spans cannot be enlarged may disappear from the map.; The unused-local-file test flag must be paired with an auxiliary crate so llvm-cov does not complain about no coverage metadata.
Test strategy: Use coverage tests with an aux crate and a testing-only discard-all or inject-unused-local-file option. Check that a used function with zero surviving regions produces no invalid metadata and that llvm-cov does not fail. Also compare MIR expectations for empty spans becoming non-empty when enlargement is performed earlier, and .cov-map cases such as async closures merging from two mappings to one.
Cases: 134497-aced4dcf1047aab08b769b34fae9d4ba7de87f04, 140847-078144fdfa7ae627d43cd919d660a71bef1e4658
Source: https://github.com/rust-lang/rust/pull/134497
Source: https://github.com/rust-lang/rust/pull/140847
> +        debug!(?covfun, "function has no mappings to embed; skipping");
> -Zcoverage-options=discard-all-spans-in-codegen
> LLVM requires all local file IDs to have at least one mapping region, and has an assertion that will fail if it detects a local file ID with no regions.
> IndexVec::<u32, _>::from_elem_n(false, covfun.virtual_file_mapping.local_file_table.len());
> in that table have no associated mapping regions, then an assertion failure

### Coverage counters need unique injection sites, self-loop-tolerant allocation, and consistent used-ID tracking
Counter identity and counter-increment injection site are distinct. Two BCB nodes or edges may share a CounterId, but there must be exactly one CounterIncrement per unique site; iterating per-BCB association maps causes duplicate increments. A BCB with a self-loop may legitimately have both a physical node counter and an incoming edge counter; rejecting that combination causes an ICE. Seen counter/expression IDs should be derived consistently from the function's coverage info/MIR, not solely from a particular codegen traversal, so inlining or instantiation differences do not rewrite used IDs to Zero.
Preconditions: Coverage instrumentation is enabled and counter/expression assignments are being allocated or emitted.; A counter ID may be associated with more than one BCB node or edge.; A coverage graph BCB may have an edge whose source and target are the same BCB.; For seen-ID tracking, the function's MIR/coverage info contains counters, expressions, and mappings; unused functions need special handling.
Pitfalls: Do not inject one increment per BCB association; inject one per unique CounterIncrementSite.; Do not assume a BCB with incoming edge counters cannot also need its own physical counter; self-loops make the combination legal.; Only BCB nodes, not edges, can have coverage spans and thus ExpressionUsed statements.; Do not initialize counters_seen empty and expressions_seen filled in a way that treats per-instance traversal as the sole truth.; Only direct MappingKind::Code(CovTerm::Expression(id)) mappings require an ExpressionUsed marker; branch/MC/DC expressions may not.; Unused functions need an explicit !is_used override to force zero mappings.
Test strategy: Create cases where a shared counter is associated with multiple nodes/edges and verify one increment per site rather than per association. Exercise a self-loop BCB with an edge counter and a physical counter to confirm no rejection. For seen IDs, compare a function whose MIR counter/expression set differs from a single instance traversal and check that mappings retain Counter/Expression terms instead of Zero, using coverage-map expectations.
Cases: 120564-2e212b79e09bce189a787a5b0c05ee5318e3c574, 122764-2f21e4f8bb86e1877d20bf74289272ecbe2bf103, 133446-6fc0fe76e8495e638a8b69461b8001437b4f319a
Source: https://github.com/rust-lang/rust/pull/120564
Source: https://github.com/rust-lang/rust/pull/122764
Source: https://github.com/rust-lang/rust/pull/133446
> This makes it possible for two nodes/edges in the coverage graph to share the same counter, without causing the instrumentor to inject unwanted duplicate counter-increment statements.
> Counter-increment statements always need to be injected.
> For most BCBs that situation would indicate an implementation bug. However, it's perfectly fine in the case of a BCB having an edge that loops back to itself.
> Given that we already have a query to identify the highest-numbered counter ID in a MIR body, we can extend that query to also build bitsets of used counter/expression IDs.
> if !self.is_used || !self.ids_info.expressions_seen.contains(id) {

### Branch coverage must compensate for `!` lowering and use block markers
Branch coverage records source-level branch conditions during MIR building, marks true/false blocks with marker statements, and converts those markers into Branch mappings during InstrumentCoverage. Unary `!` is special: MIR lowering lowers its argument and reverses then/else arms, so instrumentation must track flip parity and swap the branch orientation back. Short-circuit `&&`/`||` produce multiple conditions, and expansion-introduced branch spans are ignored.
Preconditions: Both -Cinstrument-coverage and -Zcoverage-options=branch are enabled.; The def is fn-like and not excluded by coverage attributes or derived-impl rules.; The condition is lowered through MIR match lowering; unary ! expressions are pre-visited and their parity recorded.; BlockMarker statements survive initial MIR simplification until InstrumentCoverage runs.; The branch has a non-expansion source span.
Pitfalls: Only swap then/else when is_flipped is true, and invert parity for each nested !.; Do not treat BlockMarker as an ordinary code span or codegen increment.; Branch mappings have two terms; both must be inserted into the BCB set and handled by map_terms.; Expansion-generated branch spans are intentionally ignored to reduce macro noise.; A missing marker-to-block mapping or a marker block outside the coverage graph causes that branch mapping to be dropped.; if let and let-chains are not instrumented by this implementation.
Test strategy: Use branch coverage tests with --show-branches=count and a no_merge! loop macro. Cover a, !a, !!a, !!!a, as-bool variants, && and || conditions, loops, match guards, and generic monomorphizations. Inspect .coverage branch counts and .cov-map Branch entries; for !!a the source-level expectation is True 2/False 1, while for !a it is True 1/False 2.
Cases: 122322-060c7ce7e9e09c463352a1cabd3ea1d7264deef2
Source: https://github.com/rust-lang/rust/pull/122322
> This PR adds support for branch coverage instrumentation, gated behind the unstable flag value `-Zcoverage-options=branch`.
> /// their argument instead, and then reversing the then/else arms of that `if`.
> if is_flipped {
> std::mem::swap(&mut then_block, &mut else_block);
> // For now, ignore any branch span that was introduced by

### `no-mir-spans` suppresses ordinary MIR spans but keeps signature and branch/MCDC mappings
The debugging flag -Zcoverage-options=no-mir-spans reuses the async-function signature-only treatment for all functions. It may skip ordinary span extraction from MIR statements/terminators, but it must still emit a signature mapping when a usable extended signature span exists, because llvm-cov ignores functions with no ordinary code spans. It must also continue extracting branch and MCDC mappings unconditionally.
Preconditions: Coverage instrumentation is reached for the function.; The flag is enabled via -Zcoverage-options=no-mir-spans; it is explicitly for internal debugging.; hir_info.fn_sig_span_extended may or may not be present.; Branch and MCDC markers may be present independently of ordinary MIR spans.
Pitfalls: Returning empty mappings when the flag is set can make llvm-cov drop the function entirely.; Do not skip branch or MCDC extraction along with ordinary MIR spans.; Do not duplicate divergent logic for async and no-mir-spans; one branch can handle both.; The option parser must accept the new spelling and diagnostics must list it.
Test strategy: Use branch coverage tests with -Zcoverage-options=branch,no-mir-spans and loops or conditions. Verify .cov-map shows the signature Code(Counter(0)) mapping plus branch mappings but no ordinary body code spans. Also update the invalid-value diagnostic expectation.
Cases: 126587-abc2c702af0b7b2eb36fb35839a322f5789af141
Source: https://github.com/rust-lang/rust/pull/126587
> When set, this flag skips the code that normally extracts coverage spans from MIR statements and terminators.
> if hir_info.is_async_fn || tcx.sess.coverage_no_mir_spans()
> if let Some(span) = hir_info.fn_sig_span_extended {
> // seems to ignore functions that don't have any ordinary code spans.
> branch_pairs.extend(extract_branch_pairs(mir_body, hir_info, basic_coverage_blocks));

### Nested MCDC decisions require a decision-context stack and per-depth bitmaps
MCDC instrumentation must model a boolean if-expression nested inside an outer decision as its own decision context. Lowering pushes an MCDCDecisionCtx while processing the nested expression, records separate MCDCDecision/MCDCBranch mappings with the correct decision_depth, and uses a per-depth temporary condition bitmap. A single depth-0 context/bitmap merges inner conditions into the enclosing decision and corrupts condition IDs and bitmaps.
Preconditions: MCDC coverage is requested with -Zcoverage-options=mcdc and LLVM 18 or later.; BranchInfoBuilder/MCDCState is active while lowering condition expressions.; A nested if-expression is lowered while an enclosing decision is still being processed.; The codegen side allocates as many temporary bitmaps as the maximum decision depth.
Pitfalls: Do not leave all nested conditions attached to depth 0 or reuse the enclosing decision's condition IDs.; decision_depth must flow through CondBitmapUpdate/TestVectorBitmapUpdate, BcbMappingKind, MCDCBranchSpan/MCDCDecisionSpan, and MIR pretty-printing.; Push a fresh decision context around the nested decision and pop it afterward; the stack must not become empty.; A nested decision with only one condition is intentionally left as branch coverage rather than MCDC.; Do not conflate decision depth with condition ID; nested decisions may reuse condition IDs in separate regions.
Test strategy: Add MCDC tests with one-level nested, doubly nested, nested-in-then-block, and single-condition nested decisions. Verify .coverage shows distinct MC/DC decision regions and .cov-map shows separate MCDCDecision entries with distinct bitmap_idx and branch mappings; the single-condition nested case should remain a Branch mapping.
Cases: 124255-eb422d5c7e6adccf83533ddb5a9836f6575bcd35
Source: https://github.com/rust-lang/rust/pull/124255
> it does not currently support "nested" decisions, like the following example
> This PR proposes a workaround for this cases, by introducing a Decision context stack, and by handing several `temporary condition bitmaps` instead of just one.
> On the codegen LLVM side, we allocate as many `temp_cond_bitmap`s as necessary to handle the maximum encountered decision depth.
> pub(crate) mcdc_condition_bitmap_map: RefCell<FxHashMap<Instance<'tcx>, Vec<&'ll llvm::Value>>>

### MCDC LLVM 19 migration couples condition IDs, test-vector indices, bitmap units, and span containment
Moving MC/DC instrumentation to LLVM 19 requires changing several coupled representations together: ConditionId::START=0 is a real node rather than a NONE sentinel; condition IDs are i16; temp variables accumulate test-vector indices; decision bitmaps are sized in test-vector bits, not bytes; decision mappings use an end bitmap index while branch updates use a start/test-vector offset; traversal visits false before true; and the decision span must contain all condition spans. Degraded decisions fall back to ordinary branch mappings.
Preconditions: The target LLVM is 19 or newer.; MC/DC coverage is enabled with -Zcoverage-options=mcdc and instrumentation coverage.; A function contains a boolean decision with instrumentable conditions/branches.; The decision graph is a valid DAG/tree reachable from ConditionId::START, with test-vector counts and condition counts within LLVM limits.
Pitfalls: Do not use 0 both as a real condition id and as the no-next-condition sentinel.; Do not mix old byte sizing with new test-vector bit counts.; Branch updates use the decision start bitmap_idx, but MCDCDecision uses bitmap_idx + num_test_vectors as the end index.; The temp variable accumulates cond_index; treating it as a bit position or condition id breaks verification.; Visit false before true so conditions are touched in the same order as llvm-cov.; Sort end nodes in descending num_paths order to match LLVM's bitmap-size optimization.; If the decision span does not contain all condition spans, substitute their joint span.; Decisions exceeding condition/test-vector limits should emit ordinary branch mappings and warnings.
Test strategy: Use MCDC coverage tests gated to LLVM 19 with --show-branches=count --show-mcdc. Cover a 7-condition && decision, non-tree (a || b) && c, nested decisions, inlined conditions, and degraded limit cases. Check that MCDCDecision records an end-style bitmap_idx while MCDCBranch/CondBitmapUpdate use start/test-vector offsets, and compare .cov-map and .coverage output.
Cases: 126733-acd64fa0d9e5c17de02a5b2a592163a377e33bcc
Source: https://github.com/rust-lang/rust/pull/126733
> *mcdc_bitmap_bytes += (1_u32 << decision.num_conditions).div_ceil(8);
> bitmap_idx: (decision.bitmap_idx + decision.num_test_vectors) as u32,
> let new_tv_index = self.add(current_tv_index, cond_index);
> // Note. First check the false next to ensure conditions are touched in same order with llvm-cov.
> // LLVM requires span of the decision contains all spans of its conditions.
> const MAX_CONDITIONS_IN_DECISION: usize = i16::MAX as usize;

### Coroutine-closure MIR types follow closure policy, not coroutine policy
A CoroutineClosure is closure-like even though its name contains coroutine. MIR passes should include AggregateKind::CoroutineClosure/TyKind::CoroutineClosure in the Closure policy for ZST/aggregate handling, const-prop bailout, callable ABI, and coverage aggregation. Routing it through the Coroutine policy flips all of those decisions, even though coroutines are never ZST while a zero-field coroutine-closure aggregate is handled as a ZST closure.
Preconditions: The program uses an async closure, producing TyKind::CoroutineClosure and AggregateKind::CoroutineClosure.; MIR optimization or coverage passes run over that coroutine-closure body or aggregate.; Tests should include zero-upvar coroutine closures and captured coroutine closures.
Pitfalls: Do not use the Coroutine arm for CoroutineClosure; coroutines are never ZST, but an empty-field coroutine-closure aggregate is ZST-like.; Do not omit CoroutineClosure from def-like aggregate handling.; Const-prop should bail out on ConstProp of CoroutineClosure values as unsupported.; Body ABI for a coroutine-closure is Abi::RustCall, not Abi::Rust.; Coverage must recognize AggregateKind::CoroutineClosure when collecting closure/coroutine aggregate spans.
Test strategy: Build MIR-focused tests for async closures with and without captures. Check GVN/RemoveZsts treat zero-field CoroutineClosure as ZST and def-like, const-prop bails out, AbortUnwindingCalls uses RustCall, and coverage recognizes the aggregate. Inspect emitted MIR and diagnostics rather than claiming runtime execution.
Cases: 120361-ed7fca1f8805b4348b801f23f444e0dda42f7aed
Source: https://github.com/rust-lang/rust/pull/120361
> | AggregateKind::CoroutineClosure(did, substs)
> | ty::CoroutineClosure(..)
> // Coroutines are never ZST, as they at least contain the implicit states.
> ty::CoroutineClosure(..) => Abi::RustCall,
> | AggregateKind::CoroutineClosure(..) => true,

### Closure body spans unexpand only to the closure declaration context; async signatures are special
Closure coverage spans created by macro expansion or desugaring must not be unexpanded all the way to the outermost call site. Use the nearest ancestor in the same syntax context as the closure declaration so intermediate macro context is preserved. Async functions also need an early branch that keeps only the signature span and skips normal refinement of the trivial desugared outer body. fn_sig_span must be optional because closures may have no usable signature span.
Preconditions: The function or closure is eligible for coverage instrumentation.; The closure body span was created by macro expansion or compiler desugaring and is not already in the declaration's syntax context.; For async handling, the HIR item is an async function whose outer body is a compiler-desugared wrapper.; A usable signature span shares context and filename with the body and precedes it; closures may have none.
Pitfalls: Unconditional source_callsite() unexpands too far and loses closure declaration context.; Use find_ancestor_in_same_ctxt(fn_decl_span) for closure bodies.; Do not run normal span refinement over the trivial desugared outer async function; keep only the signature span.; Only add a fake body_span.shrink_to_lo() signature span when the body yielded at least one span.; Coverage attributes on closures interact with enclosing functions; test both global and local closures.
Test strategy: Use closure-in-macro, async closure, and coverage-attribute closure fixtures. Pin closure body mappings with macro_in_closure.rs and coverage_attr_closure.rs, and update closure_macro/closure_macro_async so a closure declared inside a macro gains multiple body mappings instead of one whole-closure mapping.
Cases: 120569-a246b6be1dcd4a8ea0ac468921af7e8022686849
Source: https://github.com/rust-lang/rust/pull/120569
> Make unexpansion of closure bodies more precise, by unexpanding back to the context of the closure declaration, instead of unexpanding all the way back to the top-level context.
> Skip the normal span-refinement code when dealing with the trivial outer part of an async function.
> body_span = body_span.source_callsite();
> body_span = body_span.find_ancestor_in_same_ctxt(fn_decl_span).unwrap_or(body_span);
> Only add the signature span if we found at least one span in the body.

### Await desugaring spans must be deduplicated like branching macro spans
Await desugaring expands to a branch on the Poll discriminant. Coverage span refinement should recognize DesugaringKind::Await as well as visible bang-macro expansions, deduplicate covspans with the same span in dominator order, and retain the first such span. Otherwise await coverage depends on the future suspending and resuming, and immediately-ready awaits are not counted as expected. Only visible bang macros should be truncated/split at the macro name.
Preconditions: Coverage instrumentation is enabled for an async function containing .await.; The relevant covspan has Some(ExpnKind::Desugaring(DesugaringKind::Await)).; Covspans are sorted in dominator order before deduplication.; The awaited future may be immediately ready and never suspend.
Pitfalls: Do not treat every expansion like a visible bang macro; split only ExpnKind::Macro(MacroKind::Bang, visible_macro) spans.; Do not deduplicate non-await, non-macro spans.; Retain the first await-related or bang-macro covspan per identical span in dominator order.; The heuristic of picking only the first await-related covspan may be unreliable; test more than a ready future.; Hiding await's internal Poll branch is a span-refinement change, not a change to async lowering.
Test strategy: Add a noop-waker executor test with an async function awaiting an immediately ready future and assert the await is covered despite no suspension. Also compare async.cov-map expectations where duplicate await mappings collapse, e.g. 13 file mappings dropping to 11 and adjacent mappings merging.
Cases: 130013-25d183057edcf5d24ba0dcc8d5222a2a954aa80f
Source: https://github.com/rust-lang/rust/pull/130013
> Currently `await` is only counted towards coverage if the containing
> Similarly, `await` expands to a branch on the discriminant of `Poll`, which
> Retain only the first await-related or macro-expanded covspan with this span.
> Some(ExpnKind::Desugaring(kind)) if kind == DesugaringKind::Await => {
> I added a test to ensure the fix works in simple cases, but the heuristic of picking only the first await-related covspan might be unreliable.

### Expansion-tree parentage must follow call-site context, not ExpnData::parent
Coverage refinement can model expansions as a tree keyed by ExpnId. Each raw span is attached to its outer expansion, and tree edges must be derived from the non-dummy ExpnData::call_site context, never from ExpnData::parent. Parent-based lineage can make a macro expansion unreachable from the function body expansion, causing macros such as println! to disappear from coverage. Child expansions should contribute at most one distilled covspan, with BCB selection depending on expansion kind.
Preconditions: Coverage instrumentation extracted raw MIR spans with associated BCBs.; The function body span is the root context.; Each expansion's call_site is non-dummy and its call_site_expn_id comes from call_site.ctxt().outer_expn().; Child expansions are registered under the expansion containing their call site.
Pitfalls: Using ExpnData::parent for tree edges can silently drop macro instrumentation under #[rustfmt::skip] or similar metadata.; Filter dummy call sites before creating call-site lineage.; Do not deduplicate await/bang-macro expansions by span alone; select one BCB per child expansion in dominator order.; BCB selection is kind-dependent: bang macros and await use min_by with dominator order; other expansions use max_by.; Only truncate bang-macro call-site spans through '!'.; Use contains, eq_ctxt, and source_equal checks; discard spans outside the body or filling the entire body.
Test strategy: Add a coverage snapshot with #[rustfmt::skip] main containing a multi-line println! whose call site and argument are on separate lines. Expected .coverage/.cov-map should show body, macro call-site, and argument mappings; a parent-linked variant should lose println! instrumentation. Recheck closure and macro-in-closure cov-maps when child expansions gain call-site mappings.
Cases: 145643-c2eb45b4a176dba37a0bce8fa9c4d46cf0d55e24
Source: https://github.com/rust-lang/rust/pull/145643
> let call_site = Some(expn_data.call_site).filter(|sp| !sp.is_dummy());
> let call_site_expn_id = try { call_site?.ctxt().outer_expn() };
> // This test detects problems that can occur when building an expansion tree
> // based on `ExpnData::parent` instead of `ExpnData::call_site`, for example.

### Discard MIR spans that fill the whole function body
Coverage span extraction should discard an unexpanded MIR statement or terminator span that is source-equal to the entire function body. Such whole-body spans usually represent compiler-inserted code, notably an implicit () return, and can create a coverage region covering the whole body, making a closure's closing brace/body appear executed or inconsistent with an explicit trailing unit expression.
Preconditions: Coverage instrumentation is enabled.; A MIR statement or terminator has a span that, after unexpansion, is source-equal to the function body span.; The function may contain closures or end with an implicit () return.
Pitfalls: Do not drop all spans; only spans source-equal to the whole body should be discarded after unexpansion.; Dropping legitimate nested spans loses coverage.; Explicit trailing () versus implicit unit return can differ only in coverage rendering, so check both raw mappings and rendered regions.; Whole-body spans may also arise from macro expansion and closures.
Test strategy: Add a coverage regression with explicit_unit and implicit_unit functions containing identical closures but differing in whether () is a trailing expression. Check .cov-map bytes and .coverage regions; after the fix the implicit function's closure closing brace should not be marked executed. Also inspect existing whole-body-span tests such as coverage_attr_closure, inline-dead, macro_name_span, and unicode.
Cases: 121135-cd9021e8cb1ab6cf5bdf341d7e0538703d86fc5b
Source: https://github.com/rust-lang/rust/pull/121135
> This turns out to have been caused by the corresponding node in MIR having a span that covers the entire function body. When preparing coverage spans, any span that fills the whole body tends to cause more harm than good, so this PR detects and discards those spans.
> compiler-inserted code, e.g. the implicit return value of `()`.
> .filter(|(span, _)| !span.source_equal(body_span))

### Eager same-source span deduplication replaces pending_dups
Coverage span refinement historically kept multiple coverage spans with the same source span but different nondominating BCBs via pending_dups. A simplification sorts closure spans first and then reverse dominator order, and dedups by source equality, keeping only one span per identical source span: the closure span if present, otherwise the most-dominated BCB. This intentionally drops nondominating duplicate BCBs and changes mapping counts in macro/closure cases.
Preconditions: Initial coverage spans are built from MIR with multiple BCBs mapping to the same lo/hi source span.; Spans are fully sorted so equal-source spans are adjacent before dedup.; The same-span group may contain a closure span and/or BCBs related by dominance.
Pitfalls: Closure spans must precede non-closure spans before dedup_by so the closure representative wins.; Reverse dominator order is required to keep the most-dominated BCB.; Use span.source_equal, not raw Span equality, so macro-expansion equality is treated correctly.; dedup_by only removes adjacent equal elements; the preceding sort is an invariant.; After removing pending_dups, no path remains for special handling of overlapping duplicate spans.; The mapping count and raw bytes can change (e.g. 7 to 6); update expectations rather than assuming identical output.
Test strategy: Use closure-in-macro and async-closure coverage tests. Inspect .cov-map mapping count, raw bytes, and each Code span. Verify that a same-source duplicate pair yields one mapping, closure spans win over non-closure duplicates, and the retained BCB is the most-dominated one.
Cases: 121261-3a83b279bef65f8b727d33d1c7a80e5d2432f5aa
Source: https://github.com/rust-lang/rust/pull/121261
> But by eagerly deduplicating those extracted spans in a much simpler way, we can remove a massive chunk of complexity from the span refiner.
> There is a tradeoff here, in that we no longer try to retain *all* nondominating BCBs that have the same span, only the last one in the (semi-arbitrary) dominance ordering.
> .then_with(|| basic_coverage_blocks.cmp_in_dominator_order(a.bcb, b.bcb).reverse())
> initial_spans.dedup_by(|b, a| a.span.source_equal(b.span));
> -Number of file 0 mappings: 7

### Overlapping/refined spans are BCB-sensitive; merge only same-BCB adjacent or overlapping spans
Coverage span refinement must not combine spans from different BCBs or bridge non-adjacent source gaps. The old SpansRefiner truncated an overlapping prev using remembered merged_spans and emitted an artificial outer span; the newer function drops overlapping pending spans with different BCBs and merges only list-adjacent mergeable (same-BCB) spans. Separately, same-BCB spans may merge only when they overlap or are adjacent; otherwise intervening comments, whitespace, macro text, nested items, or holes are incorrectly attributed to the same execution count. Function signature spans are not extended to body_span.lo().
Preconditions: Input spans are already sorted within a bucket by span and relative BCB dominance.; Each SpanFromMir carries both a Span and its BasicCoverageBlock.; Earlier coverage passes have extracted/refined hole and overlap handling.; For the merge rule, two spans share a BCB but may have a non-empty source gap.
Pitfalls: Assuming identical mappings after refiner replacement is wrong; minor loop mapping changes are expected.; Using the old outer prev.span alone does not reproduce the old cutoff_statements_at behavior; it depended on merged_spans history.; Do not treat new overlap handling as ordinary interval subtraction; it is BCB-sensitive and discards overlapping different-BCB spans.; Do not merge solely because spans are adjacent in vectors; final merge requires a.is_mergeable(b), i.e. equal BCBs.; Do not merge solely on equal BCB: also require a.span.overlaps_or_adjacent(b.span).; Do not restore fn_sig_span.with_hi(body_span.lo()), which covers the signature-to-body gap.; More distinct mappings and larger raw metadata are expected after abolishing non-adjacent merges.
Test strategy: Use assert-ne and loop-break coverage tests for overlap/BCB behavior, and cleanup/branch_match_arms MIR dumps for the merge rule. Assert that same-BCB non-adjacent spans remain separate (e.g. 13:1..13:10 and 14:8..14:36 instead of 13:1..14:36), while overlapping or adjacent same-BCB spans may merge. Compare .cov-map spans and MIR mapping spans, not only line hit counts.
Cases: 126294-2fa78f3a2a87a7522d3c95bd9c53aaeede63996e, 139966-77a7ae4e9fcbf3be3988c98015d7f52137bb237c
Source: https://github.com/rust-lang/rust/pull/126294
Source: https://github.com/rust-lang/rust/pull/139966
> There is *almost* no change to the resulting coverage mappings. There are some minor changes to `loop` that on inspection appear to be neutral in terms of accuracy, with the old behaviour being a slightly-horrifying implementation detail of the old code, so I think they're acceptable.
> -        self.merged_spans.retain(|span| span.hi() <= cutoff_pos);
> Therefore, this PR aims to abolish the merging of non-adjacent coverage spans.
> Note that compatible covspans can be merged even if their underlying
> |a: &Self, b: &Self| (a.bcb == b.bcb) && a.span.overlaps_or_adjacent(b.span);
> coverage Code { bcb: bcb0 } => $DIR/instrument_coverage_cleanup.rs:13:1: 14:36 (#0);

### Hole spans come from HIR nested items and are carved or discarded, never covered as ordinary code
Closure-like regions and other nested code must be treated as holes that are removed from the enclosing function's coverage spans. Earlier hole carving was extracted into an early bucket pass that sorts and merges overlapping/adjacent holes, splits or trims enclosing spans, and refines each bucket independently. A later robustness change discards any covspan that overlaps a hole instead of splitting around it. Hole discovery must not be limited to closure-like MIR aggregate assignments: HIR should also record nested items, closures/async blocks, and inline const blocks, then keep only spans directly visible within the body span and same syntax context.
Preconditions: Coverage instrumentation is enabled and coverage spans are being extracted/refined.; The function body contains a closure, coroutine/async block, nested item, inline const block, or other hole candidate.; Hole spans are sorted and merged where overlapping or adjacent before carving.; For HIR-derived holes, the candidate span is contained in body_span and has the same syntax context.; Holes must not appear in final code mappings.
Pitfalls: Do not derive holes only from enclosing-function MIR; nested item bodies are separate and cannot be recognized there.; Do not recurse into a nested item after recording its span, but still visit items inside non-item nested bodies (NestedFilter = All).; Filter candidate HIR holes by containment and syntax context; unrelated macro-expanded spans must not be carved.; Merge overlapping or adjacent holes before carving; otherwise fragments can be lost or misordered.; Split-around-hole implementations must keep both before/after fragments and carry leftovers to later holes; the later discard-on-overlap implementation drops the whole overlapping span instead.; Re-sort each bucket if the implementation uses buckets; the refiner expects each bucket to be internally sorted.; Removing MIR hole collection must not break signature-span insertion, which then depends only on non-empty covspans.; Changing hole spans changes .cov-map layout even where line-level counts look unchanged.
Test strategy: Use holes.rs covering closures, unused nested fns, structs, impl methods, macro_rules!, inline const blocks, and async blocks; expect nested-item lines to be blank/zero while enclosing black_box lines retain counts. Use closure_macro and closure_macro_async .cov-map expectations for bucket/merge changes. Add a pair where one variant wraps a nested item in #[coverage(off)] or leaves it unused: the old MIR-closure-only holes report enclosing counts, while HIR-derived holes report blank/zero.
Cases: 125921-c57a1d1baa0a2fc4328f81be66dc7b518c1953bb, 127199-63c04f05e60ce27311fc1b874907188616beb558, 139102-26cea8a2863a3aa0fd169d8561ce77036ef6983e
Source: https://github.com/rust-lang/rust/pull/125921
Source: https://github.com/rust-lang/rust/pull/127199
Source: https://github.com/rust-lang/rust/pull/139102
> // Sort the holes, and merge overlapping/adjacent holes.
> carve_out_span_for_hole
> This makes it possible to treat more kinds of nested item/code as holes, instead of being restricted to closures.
> Fixes #126626.
> if body_span.contains(hole_span) && body_span.eq_ctxt(hole_span) {
> hir::ExprKind::Closure(_) | hir::ExprKind::ConstBlock(_) => {
> let (before, after) = covspan.split_around_hole_span(hole.span);
> .filter(|c| !c.span.overlaps(hole.span)),
> Instead of splitting spans around “holes”, just discard any span that overlaps with a hole.

### Coverage attributes are recursive and malformed attributes must not ICE in failing builds
Coverage eligibility uses the nearest #[coverage(off)] or #[coverage(on)] from the current def outward through enclosing functions, closures, modules, impl blocks, and impl-trait blocks to the crate root. No attribute defaults to enabled, and the nearest attribute wins, so an inner on can re-enable inside an outer off. Naked functions remain ineligible via an explicit NAKED check. A malformed #[coverage] attribute can still reach coverage_attr_on in an already-failing build; that unexpected-value branch must report a delayed bug rather than aborting with an ICE.
Preconditions: Compilation uses -Cinstrument-coverage and the unstable coverage_attribute feature for attribute tests.; Enclosing items/modules/impl blocks may carry coverage attributes; inner/outer and nearest-wins semantics apply.; For malformed attributes, a bare #[coverage] or other unexpected value reaches coverage_attr_on even though parser validation is expected to reject it.; The build is already failing; tests assert absence of ICE, not successful compilation.
Pitfalls: Checking only codegen_fn_attrs/direct NO_COVERAGE misses inherited attributes.; Do not treat any ancestor off as unconditional; the nearest attribute wins and an inner on can override.; Attributes on modules and impl blocks have no direct effect except as inherited defaults.; Removing NO_COVERAGE requires preserving naked-function exclusion through CodegenFnAttrFlags::NAKED.; span_delayed_bug does not make malformed code compile; normal validation errors still appear, including E0658 when the feature is disabled.; The delayed-bug message may appear alongside normal diagnostics; judge success by no internal compiler error/panic.
Test strategy: Use coverage attribute UI tests under tests/coverage/attr/ with .coverage and .cov-map expectations. Cover outer off with nested fn/closure/method, inner on overriding off, outer on with inner off, nested modules, impl and impl-trait blocks, multi-level closures, and a naked-function eligibility check. For malformed attributes, add a revisioned UI test with -Cinstrument-coverage and needs-profiler-support, asserting malformed coverage attribute input and E0658 for the no-feature revision but no internal compiler error or unexpected-value panic.
Cases: 126721-7f37f8af5f067e0f4f8d14adb7d76f013e3c4118, 131187-8e382ba022fc7f8f6f7e0abca5e8052039a81202
Source: https://github.com/rust-lang/rust/pull/126721
Source: https://github.com/rust-lang/rust/pull/131187
> This PR makes the (currently-unstable) `#[coverage(off)]` and `#[coverage(on)]` attributes apply recursively to all nested functions/closures, instead of just the function they are directly attached to.
> The current behaviour is that the attribute only affects the function that it is directly attached to.
> if tcx.codegen_fn_attrs(def_id).flags.contains(CodegenFnAttrFlags::NO_COVERAGE) {
> if tcx.codegen_fn_attrs(def_id).flags.contains(CodegenFnAttrFlags::NAKED) {
> tcx.dcx().span_bug(attr.span, "unexpected value of coverage attribute");
> // Use `span_delayed_bug` to avoid an ICE in failing builds (#127880).
> tcx.dcx().span_delayed_bug(attr.span, "unexpected value of coverage attribute");
> // Malformed `#[coverage(..)]` attributes should not cause an ICE when built
