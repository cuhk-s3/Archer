import type { ArcherConfig } from "../config.js";
import { createPiSession } from "../infra/pi.js";
import { createReviewTools, type ReviewToolContext } from "./tools.js";

export function createReviewSession(
  context: ReviewToolContext,
  config: ArcherConfig,
) {
  return createPiSession(
    config,
    context.build.patchedDir,
    createReviewTools(context),
  );
}
