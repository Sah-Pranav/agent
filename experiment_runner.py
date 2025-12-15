import asyncio
import os
import shutil
import time
from pathlib import Path
import logging
from typing import List, Dict, Any
import yaml
import csv
import sys
import subprocess
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add parent directory to path to import log_metrics_cal
sys.path.append(str(Path(__file__).parent.parent))
try:
    import log_metrics_cal
except ImportError:
    print("Error: Could not import log_metrics_cal. Make sure it exists in the parent directory.")
    sys.exit(1)

from api.agent_server.agent_client import AgentApiClient
from api.agent_server.agent_api_client import apply_patch, latest_unified_diff
from api.docker_utils import start_docker_compose, stop_docker_compose
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

TEMPLATE_ID = "nicegui_agent"
TEMPLATE_PATH = "agent/nicegui_agent/template"
LOGS_DIR = Path("logs_summary")
GENERATED_APPS_DIR = Path("generated_apps")
METRICS_FILE = Path("metrics_summary.csv")

def adjust_docker_compose(app_dir: str, project_name: str) -> None:
    """Modify docker-compose.yml in the generated app directory to use unique container names.
    This prevents Docker name conflicts when multiple runs create containers with the same static names.
    """
    compose_path = Path(app_dir) / "docker-compose.yml"
    if not compose_path.is_file():
        logger.warning(f"docker-compose.yml not found in {app_dir}, skipping adjustment")
        return
    try:
        content = compose_path.read_text()
        
        # Robust replacement: Handle both variable substitution and direct names
        # Replace postgres container name
        if "container_name: ${POSTGRES_CONTAINER_NAME:-postgres}" in content:
            content = content.replace("container_name: ${POSTGRES_CONTAINER_NAME:-postgres}", f"container_name: {project_name}_postgres")
        elif "container_name: postgres" in content:
            content = content.replace("container_name: postgres", f"container_name: {project_name}_postgres")
            
        # Replace app container name
        if "container_name: ${BACKEND_CONTAINER_NAME:-app}" in content:
            content = content.replace("container_name: ${BACKEND_CONTAINER_NAME:-app}", f"container_name: {project_name}_app")
        elif "container_name: app" in content:
            content = content.replace("container_name: app", f"container_name: {project_name}_app")
            
        # Replace network name
        if "name: ${NETWORK_NAME:-app_network}" in content:
            content = content.replace("name: ${NETWORK_NAME:-app_network}", f"name: {project_name}_network")
        elif "name: app_network" in content:
            content = content.replace("name: app_network", f"name: {project_name}_network")
            
        compose_path.write_text(content)
        logger.info(f"Adjusted docker-compose.yml for project {project_name}")
    except Exception as e:
        logger.error(f"Failed to adjust docker-compose.yml for {project_name}: {e}")

def latest_app_name_and_commit_message(events):
    """Extract the most recent app_name and commit_message from events"""
    app_name = None
    commit_message = None

    for evt in reversed(events):
        try:
            if evt.message:
                # Update app_name if found and not yet set
                if app_name is None and evt.message.app_name is not None:
                    app_name = evt.message.app_name

                # Update commit_message if found and not yet set
                if commit_message is None and evt.message.commit_message is not None:
                    commit_message = evt.message.commit_message

                # If both are set, we can break
                if app_name is not None and commit_message is not None:
                    break
        except AttributeError:
            continue

    return app_name, commit_message

def check_and_start_docker():
    """Check if Docker is running, and start it if not (macOS only)"""
    try:
        # Try to run docker ps to check if Docker is running
        result = subprocess.run(
            ["docker", "ps"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            logger.info("Docker is already running")
            return True
        else:
            logger.warning("Docker is not running. Attempting to start Docker Desktop...")
            
            # Try to start Docker Desktop on macOS
            if sys.platform == "darwin":
                subprocess.run(["open", "-a", "Docker"], check=False)
                logger.info("Waiting for Docker to start (this may take 30-60 seconds)...")
                
                # Wait for Docker to become available (max 2 minutes)
                for i in range(24):  # 24 * 5 seconds = 2 minutes
                    time.sleep(5)
                    check_result = subprocess.run(
                        ["docker", "ps"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if check_result.returncode == 0:
                        logger.info("Docker is now running!")
                        return True
                    logger.info(f"Still waiting for Docker... ({(i+1)*5}s)")
                
                logger.error("Docker did not start within 2 minutes")
                return False
            else:
                logger.error("Auto-start is only supported on macOS. Please start Docker manually.")
                return False
                
    except FileNotFoundError:
        logger.error("Docker command not found. Please install Docker.")
        return False
    except Exception as e:
        logger.error(f"Error checking/starting Docker: {e}")
        return False

def load_prompts(file_path: str) -> List[str]:
    with open(file_path, "r") as f:
        return [line.strip() for line in f if line.strip()]

def load_config(file_path: str) -> List[Dict[str, Any]]:
    with open(file_path, "r") as f:
        data = yaml.safe_load(f)
        return data.get("configs", [])

async def run_experiment(prompt: str, config: Dict[str, Any], run_id: int, csv_writer, prompt_id: int):
    config_name = config["name"]
    settings = config["settings"]
    
    logger.info(f"Starting run {run_id} with config '{config_name}'")
    
    # We'll set the final log filename after we know the app_name
    temp_log_file = LOGS_DIR / f"temp_{run_id}_{config_name}.log"
    
    # Capture logs to file
    file_handler = logging.FileHandler(temp_log_file, mode='w')
    file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    
    app_name = None  # Initialize app_name here so it's accessible in finally block
    start_time = time.time()
    
    try:
        async with AgentApiClient() as client:
            events, request = await client.send_message(
                message=prompt,
                template_id=TEMPLATE_ID,
                settings=settings
            )
            
            # Handle refinements if any (simplified loop)
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
                    template_id=TEMPLATE_ID,
                    settings=settings
                )
                # Add delay to respect rate limits
                time.sleep(10) 
                
                refinement_count += 1

            end_time = time.time()
            duration = end_time - start_time
            logger.info(f"Generation completed in {duration:.2f} seconds")

            # Extract diff and app info from events
            diff = latest_unified_diff(events)
            
            # Extract app_name from events (look backwards for the most recent one)
            for event in reversed(events):
                if event.message and hasattr(event.message, 'app_name') and event.message.app_name:
                    app_name = event.message.app_name
                    break
            
            if diff and app_name:
                # Save generated app using clean naming: {app_name}_{config}
                app_dir = GENERATED_APPS_DIR / f"{app_name}_{config_name}"
                if app_dir.exists():
                    shutil.rmtree(app_dir)
                app_dir.mkdir(parents=True, exist_ok=True)
                
                # Apply patch
                success, msg = apply_patch(diff, str(app_dir), TEMPLATE_PATH)
                if success:
                    logger.info(f"App saved to {app_dir}")
                    
                    # Deployment Logic
                    if app_dir.exists():
                        try:
                            project_name = f"{app_name}_{config_name}"
                            logger.info(f"Creating Docker containers for {app_name}...")
                            
                            # Adjust docker-compose to use unique names (prevents conflicts)
                            adjust_docker_compose(str(app_dir), project_name)
                            
                            # Start containers (creates them)
                            result = subprocess.run(
                                ["docker-compose", "up", "-d"], 
                                cwd=str(app_dir), 
                                capture_output=True,
                                text=True
                            )
                            
                            if result.returncode != 0:
                                logger.error(f"docker-compose up failed: {result.stderr}")
                                raise subprocess.CalledProcessError(result.returncode, "docker-compose up")
                            
                            logger.info(f"Containers created for {app_name}")
                            
                            # Stop them immediately (keeps them in Docker Desktop)
                            subprocess.run(
                                ["docker-compose", "stop"], 
                                cwd=str(app_dir), 
                                check=True, 
                                capture_output=True
                            )
                            logger.info(f"Containers stopped for {app_name}")
                            logger.info(f"✅ {app_name} is ready in Docker Desktop - just click 'Start' to run it")
                        except subprocess.CalledProcessError as e:
                            logger.error(f"Failed to create Docker containers for {app_name}: {e}")
                else:
                    logger.error(f"Failed to apply patch: {msg}")
            else:
                logger.warning("No diff or app name found in response")

    except Exception as e:
        logger.error(f"Experiment failed: {e}")
    finally:
        root_logger.removeHandler(file_handler)
        
        # Rename temp log file
        if app_name:
            final_log_file = LOGS_DIR / f"{app_name}_{config_name}.log"
            if temp_log_file.exists():
                if final_log_file.exists():
                    final_log_file.unlink()
                temp_log_file.rename(final_log_file)
                log_file = final_log_file
        else:
            log_file = temp_log_file
        
        # Calculate metrics
        logger.info(f"Calculating metrics for {log_file}")
        try:
            metrics = log_metrics_cal.calculate_metrics(str(log_file))
            if metrics:
                # Format timestamps
                import datetime
                start_dt = datetime.datetime.fromtimestamp(start_time)
                end_dt = datetime.datetime.fromtimestamp(end_time)
                fmt = "%Y-%m-%d %H:%M:%S"
                
                # Format duration: 13min 36sec
                duration = metrics.get("elapsed_seconds", 0.0)
                m = int(duration // 60)
                s = int(duration % 60)
                gen_time_str = f"{m}min {s}sec"
                
                # Extract stats
                g_stats = metrics["llm_stats"].get("gemini", {})
                a_stats = metrics["llm_stats"].get("claude", {})
                
                # Build status
                build_status = "success" if app_name else "failed"

                row = {
                    "prompt_id": prompt_id,
                    "config": config_name,
                    "start_time": start_dt.strftime(fmt),
                    "end_time": end_dt.strftime(fmt),
                    "gen_time": gen_time_str,
                    "build_status": build_status,
                    
                    "gemini_input_tokens": g_stats.get("input", 0),
                    "gemini_output_tokens": g_stats.get("output", 0),
                    "gemini_total_tokens": g_stats.get("total", 0),
                    "gemini_api_calls": g_stats.get("entries", 0),
                    
                    "anthropic_input_tokens": a_stats.get("input", 0),
                    "anthropic_output_tokens": a_stats.get("output", 0),
                    "anthropic_total_tokens": a_stats.get("total", 0),
                    "anthropic_api_calls": a_stats.get("entries", 0),
                    
                    "total_api_calls": metrics["entries"],
                    "app_name": app_name if app_name else "unknown",
                    "user_prompt": prompt
                }
                csv_writer.writerow(row)
                logger.info(f"Metrics recorded for {app_name if app_name else 'run'}")
            else:
                logger.warning(f"No metrics found for {log_file}")
        except Exception as e:
            logger.error(f"Failed to calculate metrics: {e}")

async def main():
    # Check and start Docker if needed
    if not check_and_start_docker():
        logger.error("Docker is not available. Cannot proceed with experiments.")
        sys.exit(1)
    
    # Ensure directories exist
    LOGS_DIR.mkdir(exist_ok=True)
    GENERATED_APPS_DIR.mkdir(exist_ok=True)
    
    prompts = load_prompts("prompts.txt")
    configs = load_config("config.yaml")
    
    # Initialize CSV file - check if it exists to add headers only on first run
    fieldnames = [
        "prompt_id", "config", "app_name", "start_time", "end_time", "gen_time", 
        "build_status", "gemini_input_tokens", "gemini_output_tokens", "gemini_total_tokens", 
        "gemini_api_calls", "anthropic_input_tokens", "anthropic_output_tokens", "anthropic_total_tokens", 
        "anthropic_api_calls", "total_api_calls", "user_prompt"
    ]
    
    file_exists = METRICS_FILE.exists()
    
    # Build a map of prompt text to prompt_id from existing CSV data
    prompt_to_id = {}
    next_prompt_id = 1
    if file_exists:
        try:
            with open(METRICS_FILE, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        prompt_id = row.get("prompt_id", "")
                        # Extract base prompt_id (handle legacy format with dots)
                        if "." in str(prompt_id):
                            base_id = int(str(prompt_id).split(".")[0])
                        else:
                            base_id = int(prompt_id) if prompt_id else 0
                        
                        prompt_text = row.get("user_prompt", "")
                        if prompt_text and base_id > 0:
                            prompt_to_id[prompt_text] = base_id
                            next_prompt_id = max(next_prompt_id, base_id + 1)
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            logger.warning(f"Could not read existing CSV to determine prompt_ids: {e}")
    
    with open(METRICS_FILE, "a", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        # Only write header if file is new
        if not file_exists:
            writer.writeheader()
        
        # Use timestamp-based run_id
        import datetime
        timestamp = int(datetime.datetime.now().timestamp())
        run_id = timestamp
        
        for prompt in prompts:
            # Check if this prompt already has an ID, otherwise assign a new one
            if prompt in prompt_to_id:
                prompt_id = prompt_to_id[prompt]
            else:
                prompt_id = next_prompt_id
                prompt_to_id[prompt] = prompt_id
                next_prompt_id += 1
            
            for config in configs:
                # Use simple prompt_id (not composite)
                await run_experiment(prompt, config, run_id, writer, prompt_id)
                csvfile.flush()
                run_id += 1

if __name__ == "__main__":
    asyncio.run(main())