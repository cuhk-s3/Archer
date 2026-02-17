import argparse
import logging
import sys
from pathlib import Path

# Add the project root to sys.path to allow imports from lms and collect
sys.path.append(str(Path(__file__).parent.parent))

from collect.prompts import PROMPT_SYSTEM_SUMMARY, PROMPT_SUMMARY
from collect.main import SimpleOpenAIClient

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description="LLVM Bug Summary Generator")
    parser.add_argument(
        "component",
        type=str,
        help="Component/Pass name (e.g., SLPVectorizer). Matches filename in passes directory.",
    )
    parser.add_argument(
        "--model", type=str, default="gpt-4o", help="Model name for LLMs"
    )
    parser.add_argument(
        "--passes-dir",
        type=str,
        default="passes",
        help="Directory containing strategy MDs",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="summary",
        help="Directory to save summaries",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode for more verbose output",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    passes_file = Path(args.passes_dir) / f"{args.component}.md"

    if not passes_file.exists():
        logger.error(f"Strategies file not found: {passes_file}")
        sys.exit(1)

    logger.info(f"Reading strategies from {passes_file}...")
    with open(passes_file, "r") as f:
        strategies_content = f.read()

    # Initialize Agent
    agent = SimpleOpenAIClient(args.model, debug=args.debug)

    # Prepare Prompts
    system_prompt = PROMPT_SYSTEM_SUMMARY.format(component=args.component)
    user_prompt = PROMPT_SUMMARY.format(
        component=args.component, strategies=strategies_content
    )

    logger.info(f"Generating summary for {args.component}...")

    agent.clear_history()
    agent.append_system_message(system_prompt)
    agent.append_user_message(user_prompt)

    try:
        response = agent.chat()

        # Save output
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{args.component}.md"

        with open(output_file, "w") as f:
            f.write(response)

        logger.info(f"Summary saved to {output_file}")

    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
