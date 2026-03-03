import asyncio
import logging
import os
import time
import sys
import shutil
import datetime
import subprocess 
from pathlib import Path
from typing import Dict, Any, List

# Core Services
from agent.core.config import AppConfig
from agent.core.docker_utils import check_and_start_docker, adjust_docker_compose, deploy_app
from agent.llm.prompt_factory import generate_similar_prompts, load_prompts
from agent.analysis import log_metrics
from agent.experiment.recorder import ExperimentRecorder

# Agent API
from api.agent_server.agent_client import AgentApiClient
from api.agent_server.agent_api_client import apply_patch, latest_unified_diff
from api.agent_server.models import MessageKind

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("experiment_runner.log")
    ]
)
logger = logging.getLogger("experiment_runner")

async def run_single_experiment(prompt: str, config: Dict[str, Any], run_id: int, 
                              recorder: ExperimentRecorder, prompt_id: int, app_config: AppConfig):
    config_name = config["name"]
    settings = config["settings"]
    
    logger.info(f"Starting run {run_id} with config '{config_name}'")
    
    temp_log_file = app_config.logs_dir / f"temp_{run_id}_{config_name}.log"
    
    # Capture logs to file
    file_handler = logging.FileHandler(temp_log_file, mode='w')
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    
    app_name = None
    start_time = time.time()
    
    try:
        async with AgentApiClient() as client:
            events, request = await client.send_message(
                message=prompt,
                template_id=app_config.template_id,
                settings=settings
            )
            
            # Simple Refinement Loop
            max_refinements = 5
            refinement_count = 0
            while (events and events[-1].message and 
                   events[-1].message.kind == MessageKind.REFINEMENT_REQUEST and 
                   refinement_count < max_refinements):
                logger.info(f"Refinement requested (attempt {refinement_count + 1})")
                events, request = await client.continue_conversation(
                    previous_events=events,
                    previous_request=request,
                    message="I approve. Proceed immediately.",
                    template_id=app_config.template_id,
                    settings=settings
                )
                time.sleep(10) 
                refinement_count += 1

            end_time = time.time()
            duration = end_time - start_time
            logger.info(f"Generation completed in {duration:.2f} seconds")

            # Extract Info
            diff = latest_unified_diff(events)
            for event in reversed(events):
                if event.message and hasattr(event.message, 'app_name') and event.message.app_name:
                    app_name = event.message.app_name
                    break
            
            # Build and Deploy
            if diff and app_name:
                app_dir = app_config.generated_apps_dir / f"{app_name}_{config_name}"
                if app_dir.exists():
                    shutil.rmtree(app_dir)
                app_dir.mkdir(parents=True, exist_ok=True)
                
                success, msg = apply_patch(diff, str(app_dir), app_config.template_path)
                if success:
                    logger.info(f"App saved to {app_dir}")
                    
                    if app_dir.exists():
                        try:
                            project_name = f"{app_name}_{config_name}"
                            adjust_docker_compose(str(app_dir), project_name)
                            if deploy_app(str(app_dir)):
                                logger.info(f"✅ {app_name} is ready in Docker Desktop - just click 'Start' to run it")
                        except Exception as e:
                            logger.error(f"Failed to create Docker containers for {app_name}: {e}")
                else:
                    logger.error(f"Failed to apply patch: {msg}")
            else:
                logger.warning("No diff or app name found")

    except Exception as e:
        logger.error(f"Experiment failed: {e}")
    finally:
        root_logger.removeHandler(file_handler)
        
        # Log Management
        log_file = temp_log_file
        if app_name:
            final_log_file = app_config.logs_dir / f"{app_name}_{config_name}.log"
            if temp_log_file.exists():
                if final_log_file.exists():
                     final_log_file.unlink()
                temp_log_file.rename(final_log_file)
                log_file = final_log_file
        
        # Metrics Calculation
        try:
            metrics = log_metrics.calculate_metrics(str(log_file))
            if metrics:
                start_dt = datetime.datetime.fromtimestamp(start_time)
                end_dt = datetime.datetime.fromtimestamp(end_time)
                
                row = {
                    "prompt_id": prompt_id,
                    "config": config_name,
                    "app_name": app_name if app_name else "unknown",
                    "start_time": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "end_time": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "gen_time": recorder.format_duration(duration),
                    "build_status": "success" if app_name else "failed",
                    "user_prompt": prompt,
                    "total_api_calls": metrics.get("entries", 0),
                    # Flatten stats
                    "gemini_input_tokens": metrics["llm_stats"].get("gemini", {}).get("input", 0),
                    "gemini_output_tokens": metrics["llm_stats"].get("gemini", {}).get("output", 0),
                    "gemini_total_tokens": metrics["llm_stats"].get("gemini", {}).get("total", 0),
                    "gemini_api_calls": metrics["llm_stats"].get("gemini", {}).get("entries", 0),
                    "anthropic_input_tokens": metrics["llm_stats"].get("claude", {}).get("input", 0),
                    "anthropic_output_tokens": metrics["llm_stats"].get("claude", {}).get("output", 0),
                    "anthropic_total_tokens": metrics["llm_stats"].get("claude", {}).get("total", 0),
                    "anthropic_api_calls": metrics["llm_stats"].get("claude", {}).get("entries", 0),
                }
                recorder.record_result(row)
        except Exception as e:
            logger.error(f"Metrics failed: {e}")

async def main():
    # 1. Initialize
    config = AppConfig()
    
    # 2. Check Infrastructure
    if not check_and_start_docker():
         sys.exit(1)
         
    config.logs_dir.mkdir(exist_ok=True)
    config.generated_apps_dir.mkdir(exist_ok=True)
    
    # 3. Load Prompts
    prompts = load_prompts("prompts.txt")
    
    # 4. Generate More?
    needed = config.target_prompt_count - len(prompts)
    if needed > 0:
        logger.info(f"Generating {needed} more prompts...")
        new_p = await generate_similar_prompts(prompts, needed)
        if new_p:
            prompts.extend(new_p)
            with open("prompts.txt", "r") as f:
                content = f.read()
            
            with open("prompts.txt", "a") as f:
                if content and not content.endswith("\n"):
                    f.write("\n")
                f.write("\n".join(new_p) + "\n")
    
    # 5. Global Review
    print(f"\n📋 PLAN: Running {len(prompts)} Experiments")
    for i, p in enumerate(prompts, 1):
        print(f"{i}. {p}")
    
    if input("\n❓ Proceed? (y/n): ").lower().strip() != 'y':
        print("❌ Cancelled.")
        sys.exit(0)

    # 6. Run Experiments
    recorder = ExperimentRecorder(config.metrics_file)
    run_id = int(datetime.datetime.now().timestamp())
    
    for prompt in prompts:
        prompt_id = recorder.get_prompt_id(prompt)
        for cfg in config.configs:
            await run_single_experiment(prompt, cfg, run_id, recorder, prompt_id, config)
            run_id += 1

if __name__ == "__main__":
    asyncio.run(main())
