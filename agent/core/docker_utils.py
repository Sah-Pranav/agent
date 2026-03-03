import subprocess
import time
import sys
import logging
from pathlib import Path

logger = logging.getLogger("experiment_runner")

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

def deploy_app(app_dir: str):
    """Start and then stop containers to ensure they are created in Docker Desktop."""
    try:
        # Start containers (creates them)
        subprocess.run(
            ["docker-compose", "up", "-d"], 
            cwd=app_dir, 
            capture_output=True,
            text=True,
            check=True
        )
        
        # Stop them immediately (keeps them in Docker Desktop)
        subprocess.run(
            ["docker-compose", "stop"], 
            cwd=app_dir, 
            check=True, 
            capture_output=True
        )
        logger.info(f"✅ App at {app_dir} deployed and stopped in Docker")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Docker deployment failed for {app_dir}: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error deploying {app_dir}: {e}")
        return False

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
