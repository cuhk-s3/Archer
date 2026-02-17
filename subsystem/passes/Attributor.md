# Issue 64959

## Incorrect Cache Management of Stack-Allocated Reachability Queries During Updates

**Description**
The bug is triggered during the update phase of an inter-procedural reachability analysis within the optimization pipeline. The analysis maintains a cache of reachability query objects, storing pointers to them to avoid redundant computations. These query objects can be either long-lived (stored permanently) or short-lived (allocated on the stack for immediate, temporary checks).

The issue arises from the logic governing the lifetime of these cached pointers. The analysis uses a state flag to indicate that it is currently iterating over and updating its set of long-lived queries. If the re-evaluation of a long-lived query necessitates a new, short-lived sub-query (allocated on the stack), the presence of the "update in progress" flag incorrectly suppresses the cleanup mechanism that normally removes temporary queries from the cache. The logic erroneously assumes that because an update is occurring, the current query object should be preserved. Consequently, when the function performing the sub-query returns and the stack frame is destroyed, the cache retains a dangling pointer to invalid memory. This memory corruption leads to assertion failures or crashes when the cache is subsequently accessed or resized.

## Example

### Original IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"

define internal i32 @recursive_reachability(i1 %cond) {
entry:
  br i1 %cond, label %if.then, label %if.else

if.then:
  %call = call i32 @recursive_reachability(i1 false)
  ret i32 %call

if.else:
  ret i32 0
}

define i32 @entry_point() {
entry:
  %call = call i32 @recursive_reachability(i1 true)
  ret i32 %call
}
```
### Optimized IR
```llvm
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"

define internal i32 @recursive_reachability(i1 %cond) {
entry:
  br i1 %cond, label %if.then, label %if.else

if.then:
  %call = call i32 @recursive_reachability(i1 false)
  ret i32 0

if.else:
  ret i32 0
}

define i32 @entry_point() {
entry:
  %call = call i32 @recursive_reachability(i1 true)
  ret i32 0
}
```
