# Issue 81561

## Missing Metadata Remapping for Debug Assignment Records during Code Cloning

**Description:**
The bug is triggered during code transformations that involve cloning instructions and their associated debug information, such as function inlining. In LLVM IR, "Assignment Tracking" links debug records to specific memory store instructions using a shared metadata identifier (`DIAssignID`). This ensures that the debugger knows which instruction is responsible for updating a variable's value in memory.

The issue occurs because the utility responsible for mapping metadata during code cloning fails to update this identifier within the non-instruction debug records. When code is cloned:
1. The store instructions are cloned, and their attached `DIAssignID` metadata is correctly mapped to a new identifier.
2. The debug records are cloned, but their internal reference to the `DIAssignID` is *not* mapped, leaving them pointing to the old identifier from the original code.

This results in a desynchronization where the cloned debug record no longer links to the cloned store instruction. When subsequent analysis passes (specifically those handling assignment tracking) attempt to resolve these links to track variable locations, they encounter an inconsistent state—mismatched or invalid identifiers—which leads to a compiler crash.

## Example

### Original IR
```llvm
define void @func_to_inline() !dbg !6 {
  %1 = alloca i32, align 4, !DIAssignID !12
  call void @llvm.dbg.assign(metadata i1 undef, metadata !10, metadata !DIExpression(), metadata !12, metadata ptr %1, metadata !DIExpression()), !dbg !13
  store i32 42, ptr %1, align 4, !DIAssignID !14
  call void @llvm.dbg.assign(metadata i32 42, metadata !10, metadata !DIExpression(), metadata !14, metadata ptr %1, metadata !DIExpression()), !dbg !13
  ret void
}

define void @caller() !dbg !15 {
  call void @func_to_inline(), !dbg !16
  ret void
}

declare void @llvm.dbg.assign(metadata, metadata, metadata, metadata, metadata, metadata)

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!3, !4}

!0 = distinct !DICompileUnit(language: DW_LANG_C99, file: !1, producer: "clang", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug)
!1 = !DIFile(filename: "test.c", directory: "/")
!3 = !{i32 2, !"Debug Info Version", i32 3}
!4 = !{i32 7, !"debug-info-assignment-tracking", i1 true}
!6 = distinct !DISubprogram(name: "func_to_inline", scope: !1, file: !1, line: 1, type: !7, isLocal: false, isDefinition: true, scopeLine: 1, unit: !0)
!7 = !DISubroutineType(types: !8)
!8 = !{null}
!10 = !DILocalVariable(name: "local", scope: !6, file: !1, line: 2, type: !11)
!11 = !DIBasicType(name: "int", size: 32, encoding: DW_ATE_signed)
!12 = distinct !DIAssignID()
!13 = !DILocation(line: 2, column: 1, scope: !6)
!14 = distinct !DIAssignID()
!15 = distinct !DISubprogram(name: "caller", scope: !1, file: !1, line: 5, type: !7, isLocal: false, isDefinition: true, scopeLine: 5, unit: !0)
!16 = !DILocation(line: 6, column: 1, scope: !15)
```
### Optimized IR
```llvm
define void @caller() !dbg !15 {
  %1 = alloca i32, align 4, !DIAssignID !20
  ; BUG: The dbg.assign below refers to !12 (the ID from the original function), 
  ; but the cloned alloca instruction above has been assigned a new ID !20.
  call void @llvm.dbg.assign(metadata i1 undef, metadata !10, metadata !DIExpression(), metadata !12, metadata ptr %1, metadata !DIExpression()), !dbg !16
  
  store i32 42, ptr %1, align 4, !DIAssignID !21
  ; BUG: The dbg.assign below refers to !14 (the ID from the original function), 
  ; but the cloned store instruction above has been assigned a new ID !21.
  call void @llvm.dbg.assign(metadata i32 42, metadata !10, metadata !DIExpression(), metadata !14, metadata ptr %1, metadata !DIExpression()), !dbg !16
  ret void
}

declare void @llvm.dbg.assign(metadata, metadata, metadata, metadata, metadata, metadata)

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!3, !4}

!0 = distinct !DICompileUnit(language: DW_LANG_C99, file: !1, producer: "clang", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug)
!1 = !DIFile(filename: "test.c", directory: "/")
!3 = !{i32 2, !"Debug Info Version", i32 3}
!4 = !{i32 7, !"debug-info-assignment-tracking", i1 true}
!6 = distinct !DISubprogram(name: "func_to_inline", scope: !1, file: !1, line: 1, type: !7, isLocal: false, isDefinition: true, scopeLine: 1, unit: !0)
!7 = !DISubroutineType(types: !8)
!8 = !{null}
!10 = !DILocalVariable(name: "local", scope: !6, file: !1, line: 2, type: !11)
!11 = !DIBasicType(name: "int", size: 32, encoding: DW_ATE_signed)
!12 = distinct !DIAssignID()
!14 = distinct !DIAssignID()
!15 = distinct !DISubprogram(name: "caller", scope: !1, file: !1, line: 5, type: !7, isLocal: false, isDefinition: true, scopeLine: 5, unit: !0)
!16 = !DILocation(line: 6, column: 1, scope: !15)
!20 = distinct !DIAssignID()
!21 = distinct !DIAssignID()
```
