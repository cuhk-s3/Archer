import { mkdir, writeFile, rename } from "node:fs/promises";
import { join, resolve } from "node:path";
import {
  createAgentSession,
  ModelRuntime,
  SessionManager,
} from "@earendil-works/pi-coding-agent";
import type { ArcherConfig } from "../config.js";

import type { ToolDefinition } from "@earendil-works/pi-coding-agent";

/** Shared Pi runtime for reviews and historical knowledge extraction. */
export async function createPiSession(
  config: ArcherConfig,
  cwd: string,
  tools: ToolDefinition[],
) {
  const agentDir = resolve(
    config.buildRoot,
    "pi-agent",
    config.model.replace(/[^A-Za-z0-9_.-]/g, "_"),
  );
  await mkdir(agentDir, { recursive: true });
  const modelConfig = {
    $schema: "https://pi.dev/schemas/models.schema.json",
    providers: {
      archer: {
        name: "Archer model endpoint",
        baseUrl: config.modelEndpoint,
        api: "openai-completions",
        apiKey: "$ARCHER_LM_API_KEY",
        models: [
          {
            id: config.model,
            name: config.model,
            reasoning: true,
            input: ["text"],
            contextWindow: 256000,
            maxTokens: 8192,
            compat: {
              thinkingFormat: "deepseek",
              requiresReasoningContentOnAssistantMessages: true,
              supportsDeveloperRole: false,
              supportsStrictMode: false,
            },
          },
        ],
      },
    },
  };
  const modelsPath = join(agentDir, "models.json");
  const temporary = `${modelsPath}.${crypto.randomUUID()}.tmp`;
  await writeFile(temporary, JSON.stringify(modelConfig, null, 2) + "\n", {
    mode: 0o600,
  });
  await rename(temporary, modelsPath);
  process.env.PI_CODING_AGENT_DIR = agentDir;
  const modelRuntime = await ModelRuntime.create({
    modelsPath,
    refreshOnCreate: false,
    allowModelNetwork: false,
  });
  const model = modelRuntime.getModel("archer", config.model);
  if (!model)
    throw new Error(`Pi did not load configured model archer/${config.model}`);
  return createAgentSession({
    cwd: cwd,
    agentDir,
    modelRuntime,
    model,
    thinkingLevel: "low",
    noTools: "builtin",
    tools: tools.map((tool) => tool.name),
    customTools: tools,
    sessionManager: SessionManager.inMemory(cwd),
  });
}
