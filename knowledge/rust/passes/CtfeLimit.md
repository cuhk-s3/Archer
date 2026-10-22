# CtfeLimit
Model: deepseek-flash
Scope: historical-transformation-program-pair; concrete tested inputs, not a current rustc bug claim or universal proof.

## Elements Frequently Missed
- Matching only ordinary calls omits explicit tail calls such as `become f()`.
- Relying on a back edge alone is insufficient when the tail-call block has no back edge.
- A Return or Goto terminator without a back edge must not be treated as a call.
- Testing only ordinary Call blocks cannot expose the omission of TailCall handling.

## Patterns Not Well Handled

### Counter every call terminator (including tail calls) and every CFG back edge
For CtfeLimit, the retained invariant is that a ConstEvalCounter must be inserted at blocks whose terminator is a call, including explicit tail calls, as well as at blocks with a CFG back edge. The historical pre-fix transformation covered only `TerminatorKind::Call` (plus back edges), so a tail-call-recursive const fn such as `become f()` lacked a counter and const evaluation could loop without termination. The corrected criterion is expressed by `if matches!(node_data.terminator().kind, TerminatorKind::Call { .. } | TerminatorKind::TailCall { .. })`, while the old omission is represented by `TerminatorKind::Call { .. }`. These programs differ deterministically for a TailCall block that has no back edge. This is a concrete historical regression description, not proof of equivalence or a claim that current compilers are defective.
Preconditions: The block terminator kind is being inspected for counter insertion.; A call-like terminator may be either an ordinary call or an explicit tail call.; Back-edge blocks are independently eligible regardless of terminator kind.
Pitfalls: Matching only ordinary calls omits explicit tail calls such as `become f()`.; Relying on a back edge alone is insufficient when the tail-call block has no back edge.; A Return or Goto terminator without a back edge must not be treated as a call.; Testing only ordinary Call blocks cannot expose the omission of TailCall handling.
Test strategy: Use concrete basic-block descriptors `(Call,false)`, `(TailCall,false)`, `(Return,false)`, `(Goto,false)`, and `(TailCall,true)`. Assert that the corrected criterion inserts a counter for both Call and TailCall blocks and for back-edge blocks. The focused differing case is a TailCall terminator with no back edge, mirroring the block produced by `become f()` in a regression test such as `const _: () = f();` followed by `become f(); //~ error: constant evaluation is taking a long time`. Also confirm Return and Goto without back edges are not treated as calls, while retaining the independent back-edge condition.
Cases: 144756-5aec4379e304ef280ee9a470e7ab121e4a81fd17
Source: https://github.com/rust-lang/rust/pull/144756
> if matches!(node_data.terminator().kind, TerminatorKind::Call { .. } | TerminatorKind::TailCall { .. })
> TerminatorKind::Call { .. }
> const _: () = f();
> become f(); //~ error: constant evaluation is taking a long time
> fixes rust-lang/rust#144753
