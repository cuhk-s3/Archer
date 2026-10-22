import type { AgentSession } from "@earendil-works/pi-coding-agent";
import type { ReviewToolContext } from "./tools.js";

export const PHASE1_TOOLS = ["rust_read", "rust_search", "rust_list", "stop"];
export const PHASE2_TOOLS = [
  "rust_read",
  "rust_search",
  "rust_list",
  "compile_rust",
  "run_miri",
  "differential_test",
  "save_knowledge",
  "submit_report",
];
export interface PhaseStats {
  phase: 1 | 2;
  startedAt: string;
  finishedAt: string;
  toolCalls: number;
}

/** Like Archer main: stop(strategy JSON) ends analysis; report ends validation. */
export async function runTwoPhases(
  session: AgentSession,
  context: ReviewToolContext,
  prompt: string,
  timeoutMs: number,
): Promise<PhaseStats[]> {
  const phases: PhaseStats[] = [];
  let calls = 0;
  let timedOut = false;
  const unsubscribe = session.subscribe((event) => {
    if (event.type === "tool_execution_start") calls++;
    // End only after the tool batch is persisted, preserving reasoning/tool history.
    if (
      event.type === "turn_end" &&
      ((context.phase === 1 && context.analysis) ||
        (context.phase === 2 && context.report))
    )
      void session.abort();
  });
  const timer = setTimeout(() => {
    timedOut = true;
    void session.abort();
  }, timeoutMs);
  try {
    for (const phase of [1, 2] as const) {
      context.phase = phase;
      const startedAt = new Date().toISOString();
      calls = 0;
      session.setActiveToolsByName(phase === 1 ? PHASE1_TOOLS : PHASE2_TOOLS);
      console.log(
        `Phase ${phase}: ${phase === 1 ? "analyze PR and submit strategies via stop" : "generate/validate tests and submit report"}`,
      );
      const instruction =
        phase === 1
          ? `${prompt}\n\nPHASE 1 ONLY: inspect source and submit your reasoning and complete structured strategy list via stop. Test execution is unavailable. Ordinary text does not end this phase.`
          : `PHASE 2: The Phase 1 strategies are frozen. Implement focused Rust tests and validate each strategy with differential_test. Pass its exact strategy name to each testing tool. Compile failures and Miri failures are not compiler bugs. Submit the evidence-backed report with submit_report. Explain coverage and limitations.\n${JSON.stringify(context.analysis, null, 2)}`;
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await session.prompt(
            attempt === 0
              ? instruction
              : `You must call ${phase === 1 ? "stop with structured strategies" : "submit_report after testing all strategies"} to finish this phase. Continue using the available tools.`,
          );
        } catch (error) {
          const committed =
            phase === 1 ? Boolean(context.analysis) : Boolean(context.report);
          // The structured tool result is already host-validated and committed.
          if (timedOut || !committed) throw error;
        }
        if (timedOut)
          throw new Error(
            `Two-phase review timed out after ${timeoutMs / 1000}s`,
          );
        const last = session.state.messages.at(-1) as
          { stopReason?: string; errorMessage?: string } | undefined;
        const committed =
          phase === 1 ? Boolean(context.analysis) : Boolean(context.report);
        if (last?.stopReason === "error" && !committed)
          throw new Error(last.errorMessage ?? "Pi model request failed");
        if (phase === 1 ? Boolean(context.analysis) : Boolean(context.report))
          break;
      }
      if (phase === 1 && !context.analysis)
        throw new Error("Phase 1 did not call stop with structured strategies");
      if (phase === 2 && !context.report)
        throw new Error("Phase 2 did not submit a report");
      phases.push({
        phase,
        startedAt,
        finishedAt: new Date().toISOString(),
        toolCalls: calls,
      });
    }
    return phases;
  } finally {
    clearTimeout(timer);
    unsubscribe();
  }
}
