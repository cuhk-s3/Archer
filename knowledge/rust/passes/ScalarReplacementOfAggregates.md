# ScalarReplacementOfAggregates
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Treating a `Drop` type as ordinary scalarizable data removes the aggregate local that owns destructor behavior; in the supplied executable model this changes the observed drop count from nonzero to `0`.
- Scalarizing enums or unions violates the documented eligibility boundaries even if their fields appear individually scalarizable.
- A retained declaration alone is insufficient if later code still rewrites field access as though the aggregate had been destructured; the whole local must remain intact.
- Do not infer a confirmed historical miscompile from these tests; the source is test-only and defines required exclusions.
- Destructuring an escaping aggregate can break address/layout assumptions about adjacent fields; the supplied comment calls this a potential miscompilation.
- A rewrite that replaces the escaping aggregate with independent locals while leaving pointer-based field access could change which storage the pointer denotes.
- The non-escaping and escaping cases must be tested separately; success on ordinary field reads does not establish that escape analysis is correct.
- Do not broaden the exclusion to all structs: the supplied description states that non-escaping uses of a struct are destructured.
- Placing deaggregated field assignments before the constant assignment violates the required ordering and may read fields before the constant is established.
- Failing to rewrite accesses from a copy of the constant can leave redundant or incorrect copy-based field reads.
- Do not conflate reads through an external pointer, such as `((*[[external]]).0`, with reads from the external aggregate, such as `([[external]].0`; the supplied checks treat these as distinct conditions.
- Ordering checks must remain anchored to the relevant function so an earlier matching `const` in another function cannot satisfy the pattern.
- An unscoped `CHECK-NOT` can pass because the forbidden pattern is absent from the current match window, even if it occurs elsewhere.
- Using only negative checks without confirming the expected replacement field accesses can miss a rewrite that neither destructures nor preserves the intended behavior.
- Assuming the static FileCheck test proves full compiler equivalence is unjustified; the supplied description explicitly states that no compiler was built or executed for that change.
- Borrowing restrictions and post-copy overwrites are distinct cases and should not be collapsed into one check.

## Patterns Not Well Handled

### SROA must preserve aggregate locals whose types are ineligible for scalarization
ScalarReplacementOfAggregates destructures eligible non-escaping struct locals into scalar fields, but must leave aggregate types that are explicitly ineligible intact. The supplied material identifies structs with a `Drop` implementation, enums, and unions as exclusions. The test-only description records `/// Check that SROA excludes structs with a `Drop` implementation.`, `/// Check that SROA excludes enums.`, and `/// Check that SROA excludes unions.` with remaining aggregate declarations/assignments. The validated program pair makes the `Drop` exclusion observable: the correct path keeps the aggregate `S` intact so `S::drop` runs and the observed count is nonzero, while the incorrect path scalarizes it into separate `Tag` locals so `S::drop` never runs and the count is `0`.
Preconditions: SROA examines the aggregate type before deciding to destructure it.; A struct with a `Drop` implementation must not be scalarized.; Enums and unions must not be scalarized, consistent with the asserted union/enum exclusion condition.; The scalarization decision must preserve destructor execution for aggregates that implement `Drop`.
Pitfalls: Treating a `Drop` type as ordinary scalarizable data removes the aggregate local that owns destructor behavior; in the supplied executable model this changes the observed drop count from nonzero to `0`.; Scalarizing enums or unions violates the documented eligibility boundaries even if their fields appear individually scalarizable.; A retained declaration alone is insufficient if later code still rewrites field access as though the aggregate had been destructured; the whole local must remain intact.; Do not infer a confirmed historical miscompile from these tests; the source is test-only and defines required exclusions.
Test strategy: Use dedicated functions for each excluded kind and assert that the aggregate local remains declared and constructed, for example `// CHECK: [[aggregate]] = S`, `// CHECK: [[enum]] = Option::<usize>::Some`, and `// CHECK: [[union]] = Repr {`. For the `Drop` case, complement static MIR checks with a concrete program where keeping the aggregate causes its destructor to increment a counter, and the incorrect scalarized variant leaves that counter at `0`.
Cases: 120455-bae4f177b8767f6acab5474c6fec2734df759a32
Source: https://github.com/rust-lang/rust/pull/120455
> /// Check that SROA excludes structs with a `Drop` implementation.
> // CHECK: [[aggregate]] = S
> /// Check that SROA excludes enums.
> // CHECK: [[enum]] = Option::<usize>::Some
> /// Check that SROA excludes unions.
> // CHECK: [[union]] = Repr {

### Escaping aggregates must not be destructured because field layout is observed
SROA must leave an escaping aggregate intact when its fields are observed through a pointer or reference. The test description explains that a non-escaping struct is destructured, while the `escaping` case retains the aggregate. It explicitly warns that destructuring the escaping case would invalidate the assumption that later fields immediately follow the first field in memory: "However, this would lead to a miscompilation because `b` and `c` might no longer appear right after `a` in memory." The checks retain `[[struct]] = Escaping {` and access fields through `&([[struct]].0` and `&raw const (*[[ref]]);`.
Preconditions: The aggregate has uses that escape through a pointer or reference, so its field layout can be observed externally.; Before destructuring, SROA must determine that all relevant aggregate uses are non-escaping.; For escaping aggregates, field addresses must continue to refer to fields of the intact aggregate.
Pitfalls: Destructuring an escaping aggregate can break address/layout assumptions about adjacent fields; the supplied comment calls this a potential miscompilation.; A rewrite that replaces the escaping aggregate with independent locals while leaving pointer-based field access could change which storage the pointer denotes.; The non-escaping and escaping cases must be tested separately; success on ordinary field reads does not establish that escape analysis is correct.; Do not broaden the exclusion to all structs: the supplied description states that non-escaping uses of a struct are destructured.
Test strategy: Include paired functions for a non-escaping struct, which should satisfy `// CHECK-NOT: [[struct]]`, and an escaping struct, which should retain `// CHECK: [[struct]] = Escaping {`. Assert the actual pointer/reference accesses with `// CHECK: [[ref]] = &([[struct]].0` and `// CHECK: [[ptr]] = &raw const (*[[ref]]);` so the test verifies both aggregate retention and field-layout observation.
Cases: 120455-bae4f177b8767f6acab5474c6fec2734df759a32
Source: https://github.com/rust-lang/rust/pull/120455
> /// Check that non-escaping uses of a struct are destructured.
> // CHECK-NOT: [foo:_.*]: Foo
> // of them to `f`. However, this would lead to a miscompilation because `b` and `c`
> // might no longer appear right after `a` in memory.
> // CHECK: [[struct]] = Escaping {
> // CHECK: [[ref]] = &([[struct]].0
> // CHECK: [[ptr]] = &raw const (*[[ref]]);

### Constant deaggregation ordering and copy-to-constant field rewrite
When SROA deaggregates assignments from a constant, the field moves must follow the constant's own assignment rather than precede it. The supplied tests also require field reads taken from a copy of a constant to be reassigned to read from the constant itself. The test description quotes the intent: deaggregated assignments from constants are placed after the constant's assignment, and "copying field accesses from the copy of the constant are reassigned to copy from the constant." The annotations show `// CHECK: [[constant]] = const`, then `// CHECK: [[t]] = move ([[constant]].0: usize)` and `// CHECK: [[u]] = move ([[constant]].1: u8)`; separate checks distinguish reads through `*[[external]]` from reads from `[[external]]`.
Preconditions: SROA is rewriting an aggregate initialized from a constant.; The constant assignment exists as an ordered MIR statement before its deaggregated field uses.; Field accesses originating from a copy of the constant are recognizable and can be redirected to the constant source.; Borrowing/indirect-access behavior and ordinary copy reads are distinguished when rewriting field access.
Pitfalls: Placing deaggregated field assignments before the constant assignment violates the required ordering and may read fields before the constant is established.; Failing to rewrite accesses from a copy of the constant can leave redundant or incorrect copy-based field reads.; Do not conflate reads through an external pointer, such as `((*[[external]]).0`, with reads from the external aggregate, such as `([[external]].0`; the supplied checks treat these as distinct conditions.; Ordering checks must remain anchored to the relevant function so an earlier matching `const` in another function cannot satisfy the pattern.
Test strategy: In a dedicated constant function, assert the ordered sequence `// CHECK: [[constant]] = const`, then the field moves from that constant. Add checks for the copy-based field rewrite, including the distinction between `// CHECK: [[byte]] = ((*[[external]]).0` and `// CHECK: [[byte]] = ([[external]].0`. Keep each sequence under its own `CHECK-LABEL` anchor.
Cases: 120455-bae4f177b8767f6acab5474c6fec2734df759a32
Source: https://github.com/rust-lang/rust/pull/120455
> /// Check that deaggregated assignments from constants are placed after the constant's
> /// assignment. Also check that copying field accesses from the copy of the constant are
> /// reassigned to copy from the constant.
> // CHECK: [[constant]] = const
> // CHECK: [[t]] = move ([[constant]].0: usize)
> // CHECK: [[u]] = move ([[constant]].1: u8)
> // CHECK: [[byte]] = ((*[[external]]).0
> // CHECK: [[byte]] = ([[external]].0

### Scoped FileCheck assertions for SROA eligibility and rewrite boundaries
SROA coverage is organized by per-function assertions that distinguish destructuring from retention across eligibility boundaries. The supplied test-only description lists dedicated cases for `dropping`, `enums`, `structs`, `unions`, `flat`, `escaping`, `copies`, `ref_copies`, and `constant`, using FileCheck checks and `CHECK-NOT` to prove a local disappeared or remained. The description emphasizes that `CHECK-NOT` must be scoped with `CHECK-LABEL` so absence in one function does not mask presence in another. These are static MIR assertions; no compiler execution or historical miscompile reproduction is claimed by the test-only change.
Preconditions: Each function or boundary case has its own `CHECK-LABEL` anchor before checks and `CHECK-NOT` assertions.; Positive retention checks name the aggregate type or construction, while destructuring checks assert the aggregate local is absent.; Expectations encode SROA-specific eligibility, ordering, and field-rewrite behavior rather than generic MIR shape.
Pitfalls: An unscoped `CHECK-NOT` can pass because the forbidden pattern is absent from the current match window, even if it occurs elsewhere.; Using only negative checks without confirming the expected replacement field accesses can miss a rewrite that neither destructures nor preserves the intended behavior.; Assuming the static FileCheck test proves full compiler equivalence is unjustified; the supplied description explicitly states that no compiler was built or executed for that change.; Borrowing restrictions and post-copy overwrites are distinct cases and should not be collapsed into one check.
Test strategy: Use `// unit-test: ScalarReplacementOfAggregates` with `// compile-flags: -Cpanic=abort` and `// no-prefer-dynamic`, then place `CHECK-LABEL` anchors for each function. Assert destructuring with scoped `// CHECK-NOT: [[struct]]` or `// CHECK-NOT: [foo:_.*]: Foo`, assert exclusions with positive aggregate checks, and assert constant ordering and field rewrites with ordered `CHECK` lines. Treat these FileCheck results as targeted static evidence, not as a proof of compiler-wide equivalence.
Cases: 120455-bae4f177b8767f6acab5474c6fec2734df759a32
Source: https://github.com/rust-lang/rust/pull/120455
> // CHECK-NOT: [[struct]]
> // CHECK-LABEL: fn dropping(
> // CHECK-NOT: [foo:_.*]: Foo
> // CHECK: [[aggregate]] = S
> // CHECK: [[enum]] = Option::<usize>::Some
> // CHECK: [[union]] = Repr {
