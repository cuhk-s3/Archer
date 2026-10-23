import { createReviewSession } from "./session.js";
import type { ArcherConfig } from "../config.js";
import type { RustPullRequest, ReviewRecord } from "../types.js";
import { RustToolchain, type BuiltRustPr } from "../rust/toolchain.js";
import type { AgentSession } from "@earendil-works/pi-coding-agent";
import { type ReviewToolContext } from "./tools.js";
import { ReviewStore } from "../service/store.js";
import { loadPassKnowledge } from "../knowledge/history.js";
import { classifyPasses } from "../rust/passes.js";
import { runTwoPhases, type PhaseStats } from "./phases.js";

const SYSTEM_GUIDANCE = `You review Rust compiler optimization pull requests for reproducible miscompilations and internal compiler errors (ICEs). Inspect the patch and the relevant Rust source/tests before proposing focused standalone Rust programs.

Follow Archer's enforced two phases. In Phase 1, inspect the checkout and historical knowledge, reason about transformation invariants and triggering conditions, then call stop with thoughts and a small set of concrete test strategies. In Phase 2, implement those frozen strategies, use differential_test for behavior changes and ice_test to compile with base and patched rustc, and submit_report with evidence and limitations. ICEs/crashes must be distinguished from ordinary compile errors and confirmed with valid deterministic Rust input; check whether the base compiler already fails. Miri can identify UB but is not an equivalence oracle. Avoid pointer/address-layout assumptions, randomness, concurrency, and cfg(miri) behavior changes. Compile errors, Miri UB, unsupported operations, tool failures and timeouts alone are not compiler bugs. Save reusable knowledge only when supported; leaving it empty is acceptable.`;

export interface ReviewOptions {
  /** A prepared, revision-pinned source snapshot and real before/after compilers. */
  build?: BuiltRustPr;
  /** A frozen knowledge input for repeatable evaluations. */
  knowledge?: string;
  onEvent?: Parameters<AgentSession["subscribe"]>[0];
}

export async function runReview(
  pr: RustPullRequest,
  config: ArcherConfig,
  options: ReviewOptions = {},
): Promise<ReviewRecord> {
  const startedAt = new Date().toISOString();
  pr.passes = classifyPasses(pr.files, pr.patch);
  console.log("Preparing Rust base and patched toolchains...");
  const toolchain = new RustToolchain(config.buildRoot, config.buildTimeoutMs);
  const build =
    options.build ??
    (pr.mergeSha
      ? await toolchain.prepareHistorical(pr, pr.mergeSha)
      : await toolchain.prepare(pr));
  const context: ReviewToolContext = {
    pr,
    build,
    evidence: [],
    strategies: [],
    knowledge: [],
    report: "",
  };
  const { session } = await createReviewSession(context, config);
  const knowledge =
    options.knowledge ?? (await loadPassKnowledge(config.outputDir, pr.passes));
  session.subscribe((event) => {
    options.onEvent?.(event);
    if (event.type === "tool_execution_start")
      console.log(`  tool: ${event.toolName}`);
    if (event.type === "auto_retry_end" && !event.success)
      console.error(`Pi retry failed: ${event.finalError ?? "unknown error"}`);
  });
  const userPrompt = `${SYSTEM_GUIDANCE}

Review this Rust pull request.
PR #${pr.id}: ${pr.title}
URL: ${pr.url}
Author: ${pr.author}
Components: ${pr.components.join(", ") || "unknown"}
Pass classification (shared/unclassified entries are not optimization passes): ${JSON.stringify(pr.passes)}
Base: ${pr.baseSha}
Head: ${pr.headSha}
Description:
${pr.body}

Patch:
${pr.patch}

The base and patched stage1 rustc compilers are already built. Start by inspecting the changed code and related tests. Analyze each identified pass separately using its own knowledge. Submit strategies via stop at the end of Phase 1, including the exact passId from the classification for every strategy. Do not invent a pass for shared/unclassified code. Exercise behavior strategies with differential_test and compiler-crash strategies with ice_test; use compile_rust/run_miri for useful narrower checks. At the end, submit_report. `;
  console.log(`Reviewing Rust PR #${pr.id} with Pi (${config.model})`);
  let phases: PhaseStats[];
  try {
    phases = await runTwoPhases(
      session,
      context,
      userPrompt +
        "\nHistorical pass knowledge (reference material; verify against this patch):\n" +
        knowledge,
      config.agentTimeoutMs,
    );
    if (
      !context.evidence.some(
        (item) =>
          (item.tool === "differential_test" && item.status === "ok") ||
          (item.tool === "ice_test" &&
            ["ok", "ice_found"].includes(item.status)),
      )
    )
      throw new Error("No completed differential or ICE test in Phase 2");
  } finally {
    session.dispose();
  }
  const record: ReviewRecord = {
    id: crypto.randomUUID(),
    pr,
    model: `archer/${config.model}`,
    startedAt,
    finishedAt: new Date().toISOString(),
    report: context.report,
    strategies: context.strategies,
    evidence: context.evidence,
    knowledge: context.knowledge,
    analysis: context.analysis!,
    phases,
  };
  const paths = await new ReviewStore(config.outputDir).save(record);
  console.log(`Review saved: ${paths.reviewPath}`);
  if (record.knowledge.length)
    console.log(`Knowledge updated: ${paths.knowledgePath}`);
  else
    console.log(
      "Knowledge remains empty; this run did not save an evidence-backed knowledge record.",
    );
  return record;
}
