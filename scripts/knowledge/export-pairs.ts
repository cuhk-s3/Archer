import { getKnowledgeConfig } from "../../src/config.js";
import { exportPairArtifacts } from "../../src/knowledge/verification/artifacts.js";
await exportPairArtifacts(getKnowledgeConfig());
