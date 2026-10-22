import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { projectRoot } from "../config.js";

export interface PassDefinition {
  id: string;
  name: string;
  module: string;
  sourceUrls: string[];
}
export interface PassAssignment {
  id: string;
  name: string;
  kind: "pass" | "shared" | "unclassified";
  confidence: "high" | "medium" | "unresolved";
  evidence: string[];
}
export function catalogFromSnapshots(
  snapshots: Array<{ source: string; url: string }>,
): PassDefinition[] {
  const passes = new Map<string, PassDefinition>();
  const add = (name: string, module: string, url: string) => {
    const id = name;
    const item = passes.get(id) ?? { id, name, module, sourceUrls: [] };
    if (!item.sourceUrls.includes(url)) item.sourceUrls.push(url);
    passes.set(id, item);
  };
  // Registered names are authoritative; enum variants are not separate passes.
  for (const { source, url } of snapshots) {
    for (const match of source.matchAll(
      /^\s*(?:pub\s+)?mod\s+(\w+)\s*:\s*([^;]+);/gm,
    )) {
      const names = match[2]!
        .replace(/\{[^}]*\}/g, "")
        .split(",")
        .map((part) => part.trim());
      for (const name of names)
        if (/^[A-Z]\w*$/.test(name)) add(name, match[1]!, url);
    }
  }
  for (const { source, url } of snapshots) {
    const modules = new Set(
      [...source.matchAll(/^\s*(?:pub\s+)?mod\s+(\w+)\s*;/gm)].map(
        (m) => m[1]!,
      ),
    );
    for (const match of source.matchAll(
      /&\s*(?:Lint\s*\(\s*)?(\w+)::([A-Z]\w+)/g,
    )) {
      const module = match[1]!;
      const name = match[2]!;
      if (!modules.has(module)) continue;
      const known = [...passes.values()].filter(
        (pass) => pass.module === module,
      );
      if (!known.length || passes.has(name)) add(name, module, url);
    }
  }
  return [...passes.values()].sort((a, b) => a.id.localeCompare(b.id));
}
let cache: PassDefinition[] | undefined;
export function getPassCatalog(): PassDefinition[] {
  cache ??= JSON.parse(
    readFileSync(
      resolve(projectRoot, "knowledge/rust/catalog/pass-catalog.json"),
      "utf8",
    ),
  ).passes;
  return cache!;
}

/** Source paths + exact MIR dump/registration names, never a title-only guess. */
export function classifyPasses(
  files: string[],
  patch: string,
  catalog = getPassCatalog(),
): PassAssignment[] {
  const result = new Map<string, PassAssignment>();
  const add = (
    id: string,
    kind: PassAssignment["kind"],
    confidence: PassAssignment["confidence"],
    evidence: string,
  ) => {
    const item = result.get(id) ?? {
      id,
      name: id,
      kind,
      confidence,
      evidence: [],
    };
    if (!item.evidence.includes(evidence)) item.evidence.push(evidence);
    if (confidence === "high") item.confidence = "high";
    result.set(id, item);
  };
  const changedLines = patch
    .split("\n")
    .filter((line) => /^[+-](?![+-])/.test(line))
    .map((line) => line.slice(1))
    .join("\n");
  const hasName = (text: string, name: string) =>
    new RegExp(`\\b${name}\\b`).test(text);
  for (const file of files) {
    const module = file.match(
      /^compiler\/rustc_mir_transform\/src\/([^/.]+)(?:\.rs|\/)/,
    )?.[1];
    if (module && module !== "lib") {
      const matches = catalog.filter((p) => p.module === module);
      if (matches.length === 1)
        add(matches[0]!.id, "pass", "high", `implementation: ${file}`);
      else if (matches.length > 1) {
        const segment =
          patch
            .split(/^diff --git /m)
            .find((part) => part.startsWith(`a/${file} b/${file}`)) ?? "";
        const scopedChanges = segment
          .split("\n")
          .filter((line) => /^@@|^[+-](?![+-])/.test(line))
          .join("\n");
        const mentioned = matches.filter((p) => hasName(scopedChanges, p.name));
        for (const pass of mentioned.length ? mentioned : matches)
          add(
            pass.id,
            "pass",
            mentioned.length ? "high" : "medium",
            `shared implementation file: ${file}${mentioned.length ? "; name present in diff" : "; pass ambiguous"}`,
          );
      } else if (["ssa", "liveness", "cost_checker"].includes(module))
        add(`shared-${module}`, "shared", "high", `analysis/helper: ${file}`);
      else if (["pass_manager", "patch", "cross_crate_inline"].includes(module))
        add(`shared-${module}`, "shared", "high", `pipeline/helper: ${file}`);
      else
        add(
          "unclassified-mir",
          "unclassified",
          "unresolved",
          `No registered pass matched: ${file}`,
        );
    }
    if (file === "compiler/rustc_mir_transform/src/lib.rs") {
      const named = catalog.filter((p) => hasName(changedLines, p.name));
      for (const pass of named)
        add(
          pass.id,
          "pass",
          "medium",
          `pass registration/pipeline change: ${file}`,
        );
      if (!named.length)
        add("shared-pipeline", "shared", "high", `pipeline: ${file}`);
    }
    if (file.startsWith("tests/mir-opt/")) {
      for (const pass of catalog) {
        if (new RegExp(`\\.${pass.name}(?:[.\\-]|$)`).test(file))
          add(pass.id, "pass", "high", `MIR dump: ${file}`);
      }
    }
    if (file.startsWith("compiler/rustc_mir_dataflow/"))
      add("shared-dataflow", "shared", "high", `dataflow analysis: ${file}`);
    if (file.startsWith("compiler/rustc_middle/src/mir/"))
      add("shared-mir-ir", "shared", "high", `MIR IR: ${file}`);
  }
  // EMIT_MIR and explicit pass flags identify a pass even for test-only fixes.
  for (const line of changedLines
    .split("\n")
    .filter((s) =>
      /EMIT_MIR|mir-enable-passes|unit-test:|test-mir-pass:/.test(s),
    )) {
    for (const pass of catalog)
      if (hasName(line, pass.name)) add(pass.id, "pass", "high", line.trim());
  }
  if (!result.size)
    add(
      "unclassified-non-mir",
      "unclassified",
      "unresolved",
      "No concrete MIR pass identified; do not treat a crate or backend as an optimization pass",
    );
  return [...result.values()].sort((a, b) => a.id.localeCompare(b.id));
}
