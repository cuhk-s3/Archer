import type { ToolDefinition } from "@earendil-works/pi-coding-agent";
import type { ArcherConfig } from "../config.js";
import { projectRoot } from "../config.js";
import { createPiSession } from "../infra/pi.js";

/** Each knowledge role gets a separate in-memory conversation. */
export async function runKnowledgeAgent(
  config: ArcherConfig,
  tools: ToolDefinition[],
  prompt: string,
  committed: () => boolean,
): Promise<void> {
  const { session } = await createPiSession(config, projectRoot, tools);
  let timedOut = false;
  const unsubscribe = session.subscribe((event) => {
    if (event.type === "turn_end" && committed()) void session.abort();
  });
  const timer = setTimeout(() => {
    timedOut = true;
    void session.abort();
  }, config.agentTimeoutMs);
  try {
    try {
      await session.prompt(prompt);
    } catch (error) {
      if (!committed() || timedOut) throw error;
    }
    const last = session.state.messages.at(-1) as
      { stopReason?: string; errorMessage?: string } | undefined;
    if (timedOut) throw new Error("Knowledge agent timed out");
    if (last?.stopReason === "error" && !committed())
      throw new Error(last.errorMessage ?? "Knowledge model request failed");
    if (!committed())
      throw new Error("Knowledge agent did not submit a structured result");
  } finally {
    clearTimeout(timer);
    unsubscribe();
    session.dispose();
  }
}
