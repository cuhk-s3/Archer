import { getKnowledgeConfig } from "../../src/config.js";
import { publishPassKnowledge } from "../../src/knowledge/publication.js";
await publishPassKnowledge(getKnowledgeConfig());
