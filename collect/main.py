import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

# Add the project root to sys.path to allow imports from lms and collect
sys.path.append(str(Path(__file__).parent.parent))

from collect.prompts import (
    PROMPT_ANALYZE,
    PROMPT_SYSTEM_ANALYZE,
    PROMPT_SYSTEM_VERIFY,
    PROMPT_VERIFY,
)
from lms.openai import OpenAIAgent

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="LLVM Bug Analysis and Test Case Generation"
    )
    parser.add_argument(
        "--issue", type=str, required=True, help="Issue ID (e.g., 100298)"
    )
    parser.add_argument(
        "--model", type=str, default="gpt-4o", help="Model name for LLMs"
    )
    parser.add_argument(
        "--dataset-dir", type=str, default="dataset", help="Path to dataset directory"
    )
    parser.add_argument(
        "--passes-dir",
        type=str,
        default="collect/passes",
        help="Directory to save strategy MDs",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="collect/output",
        help="Directory to save generated IRs and verification results",
    )
    return parser.parse_args()


def load_issue_data(dataset_dir: str, issue_id: str):
    # Construct path assuming the dataset structure provided
    dataset_path = Path(dataset_dir)
    json_path = dataset_path / f"{issue_id}.json"

    if not json_path.exists():
        # Fallback: check if the dataset dir contains the json files flatly
        # or if the user provided the full path to json
        if Path(issue_id).exists() and str(issue_id).endswith(".json"):
            json_path = Path(issue_id)
        else:
            raise FileNotFoundError(f"Issue file not found: {json_path}")

    with open(json_path, "r") as f:
        data = json.load(f)
    return data


def analyze_bug(agent: OpenAIAgent, data: dict, issue_id: str, passes_dir: str):
    # Extract required fields
    bug_type = data.get("bug_type", "unknown")

    # Try to find component/pass name
    components = data.get("hints", {}).get("components", [])
    component_str = ", ".join(components) if components else "unknown"

    # Using issue body and patch
    issue_body = data.get("issue", {}).get("body", "")
    patch = data.get("patch", "")

    # Fill prompt
    prompt = PROMPT_ANALYZE.format(
        bug_type=bug_type, component=component_str, issue=issue_body, patch=patch
    )

    logger.info(f"Analyzing bug {issue_id}...")

    # Reset agent history for new task
    agent.clear_history()
    agent.append_system_message(PROMPT_SYSTEM_ANALYZE)
    agent.append_user_message(prompt)

    # Use a customized chat interaction since we don't need tools here
    # The run method expects handlers, but we can simulate a simple interaction
    # Or just use the model directly if possible? AgentBase.run is designed for tool loops.
    # We can provide a mocked handler that always stops.
    response_content = []

    def simple_response_handler(content):
        response_content.append(content)
        return False, content  # Return False to stop the loop

    def simple_tool_handler(name, args, result):
        return False, ""

    agent.run([], simple_response_handler, simple_tool_handler)

    analysis_result = "".join(response_content)

    # Save to file
    md_paths = []
    if not components:
        components = ["unknown"]

    for comp in components:
        # Sanitize it
        safe_pass_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", comp)
        output_path = Path(passes_dir) / f"{safe_pass_name}.md"

        # Ensure directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            f.write(analysis_result)

        logger.info(f"Analysis saved to {output_path}")
        md_paths.append(output_path)

    return md_paths, analysis_result


def generate_and_verify(
    agent: OpenAIAgent, strategy: str, issue_id: str, output_dir: str
):
    logger.info(f"Generating LLVM IR for bug {issue_id} based on strategy...")

    # Reset agent history
    agent.clear_history()
    agent.append_system_message(PROMPT_SYSTEM_VERIFY)
    prompt = PROMPT_VERIFY.format(strategy=strategy)
    agent.append_user_message(prompt)

    response_content = []

    def simple_response_handler(content):
        response_content.append(content)
        return False, content

    def simple_tool_handler(name, args, result):
        return False, ""

    agent.run([], simple_response_handler, simple_tool_handler)

    generation_result = "".join(response_content)

    # Extract JSON
    original_ir = None
    optimized_ir = None

    try:
        # Find JSON block
        match = re.search(r"```json\s*(.*?)\s*```", generation_result, re.DOTALL)
        if match:
            json_str = match.group(1)
        elif generation_result.strip().startswith(
            "{"
        ) and generation_result.strip().endswith("}"):
            json_str = generation_result
        else:
            logger.error("Could not find JSON in LLM output")
            return

        test_case = json.loads(json_str)
        original_ir = test_case.get("original_ir", "")
        optimized_ir = test_case.get("optimized_ir", "")

        if not original_ir or not optimized_ir:
            logger.error("Generated JSON missing original_ir or optimized_ir")
            return

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        return

    # Verify with alive-tv
    alive_tv_path = os.environ.get("LAB_LLVM_ALIVE_TV")
    if not alive_tv_path:
        logger.error(
            "LAB_LLVM_ALIVE_TV environment variable not set. Skipping verification."
        )
        return

    # Use tempfile to store IRs
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".ll", delete=False) as src_file:
        src_file.write(original_ir)
        src_path = src_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".ll", delete=False) as tgt_file:
        tgt_file.write(optimized_ir)
        tgt_path = tgt_file.name

    logger.info(f"Running alive-tv on {src_path} and {tgt_path}...")

    verification_success = False
    try:
        # alive-tv usage: alive-tv source.ll target.ll
        cmd = [alive_tv_path, src_path, tgt_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if "Transformation seems to be correct" in result.stdout:
            logger.info("Verification Result: EQUIVALENT")
            verification_success = False
        elif "Transformation doesn't verify" in result.stdout:
            logger.info("Verification Result: NOT EQUIVALENT (Bug Reproduced!)")
            verification_success = True
        else:
            logger.info("Verification Result: UNKNOWN")

    except Exception as e:
        logger.error(f"Error running alive-tv: {e}")
    finally:
        # Clean up temp files
        if os.path.exists(src_path):
            os.remove(src_path)
        if os.path.exists(tgt_path):
            os.remove(tgt_path)

    if verification_success:
        return original_ir, optimized_ir
    return None, None


def main():
    args = parse_args()

    try:
        data = load_issue_data(args.dataset_dir, args.issue)
    except Exception as e:
        logger.error(str(e))
        return

    # 1. Analyze
    try:
        # We instantiate agent for each step or reuse.
        # Assuming args.model is valid.
        agent1 = OpenAIAgent(args.model)
        md_paths, strategy = analyze_bug(agent1, data, args.issue, args.passes_dir)
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return

    # 2. Generate and Verify
    try:
        agent2 = OpenAIAgent(args.model)
        src_ir, tgt_ir = generate_and_verify(
            agent2, strategy, args.issue, args.output_dir
        )

        if src_ir and tgt_ir and md_paths:
            for md_path in md_paths:
                with open(md_path, "a") as f:
                    f.write("\n\n## Example\n\n")
                    f.write("### Original IR\n")
                    f.write("```llvm\n")
                    f.write(src_ir)
                    f.write("\n```\n")
                    f.write("### Optimized IR\n")
                    f.write("```llvm\n")
                    f.write(tgt_ir)
                    f.write("\n```\n")
                logger.info(f"Verified example appended to {md_path}")

    except Exception as e:
        logger.error(f"Generation/Verification failed: {e}")


if __name__ == "__main__":
    main()
