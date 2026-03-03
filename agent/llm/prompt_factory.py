import os
import sys
import logging
import time
import subprocess
import urllib.request
import re
from typing import List
from . import common
from .common import Message, TextRaw

logger = logging.getLogger("experiment_runner")

def load_prompts(file_path: str) -> List[str]:
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r") as f:
        # Strip whitespace and ignore empty lines
        return [line.strip() for line in f if line.strip()]

def check_ollama_running() -> bool:
    """Check if Ollama is running, and if not, attempt to start it (on macOS)."""
    try:
        # Check if Ollama is responsive
        try:
            # Check standard ollama port
            with urllib.request.urlopen("http://localhost:11434/", timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionRefusedError):
            pass  # Not running
            
        logger.warning("Ollama is not running. Attempting to start Ollama...")
        
        if sys.platform == "darwin":
            # -g: Do not bring to foreground (background launch)
            # Use the App so user can see it running in Dock/Menu bar
            subprocess.run(["open", "-g", "-a", "Ollama"], check=False)
            logger.info("Waiting for Ollama to start (this may take 10-20 seconds)...")
            
            # Wait for Ollama loop
            for i in range(20):
                time.sleep(2)
                try:
                    with urllib.request.urlopen("http://localhost:11434/", timeout=2) as response:
                        if response.status == 200:
                            logger.info("Ollama is now running!")
                            time.sleep(2)  # Give it a moment to stabilize
                            return True
                except:
                    pass
                logger.info(f"Still waiting for Ollama... ({(i+1)*2}s)")
            
            logger.error("Ollama did not start within 40 seconds")
            return False
        else:
            logger.error("Auto-start is only supported on macOS. Please start Ollama manually.")
            return False
            
    except Exception as e:
        logger.error(f"Error checking/starting Ollama: {e}")
        return False

async def generate_similar_prompts(existing_prompts: List[str], count_needed: int) -> List[str]:
    """Generate similar but distinct web app ideas using Gemini."""
    logger.info(f"Generating {count_needed} new prompts using Gemini...")
    
    system_prompt = "You are a creative assistant that generates web app ideas for coding experiments."
    prompt_text = (
        f"Here are {len(existing_prompts)} existing app ideas:\n"
        + "\n".join([f"- {p}" for p in existing_prompts])
        + f"\n\nGenerate {count_needed} NEW, DISTINCT web app ideas that are similar in complexity and style (simple, self-contained, using Frankfurter/OpenMeteo/etc if relevant, or just logic). "
        + "Return ONLY the new prompts, one per line. Do not number them. Do not include intro text."
    )

    
    try:
        # Determine provider based on model name
        # Allow checking specific env var first, then universal fallback
        model_name = os.getenv("PROMPT_GENERATION_MODEL", os.getenv("LLM_UNIVERSAL_MODEL", "gemini-flash-latest"))
        llm = None
        
        if model_name.startswith("claude"):
            # Anthropic
            from agent.llm.anthropic_client import AnthropicLLM
            llm = AnthropicLLM(model_name=model_name)
            logger.info(f"Using Anthropic model: {model_name}")
            
        elif model_name.startswith("gemini"):
            # Gemini
            # Handle aliases for Gemini 1.5/Flash
            if model_name in ["gemini-flash", "gemini-1.5-flash", "gemini-1.5-flash-001"]:
                model_name = "gemini-flash-latest"
            
            from agent.llm.gemini import GeminiLLM
            llm = GeminiLLM(model_name=model_name)
            logger.info(f"Using Gemini model: {model_name}")
            
        else:
            # Fallback to Ollama for local models, BUT check if running first
            if not check_ollama_running():
                logger.warning("Ollama is not running. Falling back to Gemini (gemini-flash-latest).")
                model_name = "gemini-flash-latest"
                from agent.llm.gemini import GeminiLLM
                llm = GeminiLLM(model_name=model_name)
                logger.info(f"Using Gemini model (fallback): {model_name}")
            else:
                try:
                    from agent.llm.ollama_client import OllamaLLM
                    llm = OllamaLLM(model_name=model_name)
                    logger.info(f"Using Ollama model: {model_name}")
                except ImportError:
                    logger.error("Ollama client not available. Falling back to Gemini.")
                    model_name = "gemini-flash-latest"
                    from agent.llm.gemini import GeminiLLM
                    llm = GeminiLLM(model_name=model_name)
        
        response = await llm.completion(
            messages=[Message(role="user", content=[TextRaw(text=prompt_text)])],
            max_tokens=4096,
            system_prompt=system_prompt
        )
        
        new_prompts = []
        try:
            if response.content:
                text_content = ""
                for block in response.content:
                     # Check isinstance OR class name to avoid import mismatch issues
                     if isinstance(block, TextRaw) or type(block).__name__ == "TextRaw":
                         text_content += block.text
                
                if text_content:
                    # Split by lines and process each
                    lines = text_content.strip().splitlines()

                    
                    for idx, line in enumerate(lines):
                        line = line.strip()
                        
                        # Skip empty lines
                        if not line:
                            continue
                        
                        # Skip headers (all caps, markdown headers, or standalone bold)
                        if line.isupper() or line.startswith('#'):
                            continue
                        if line.startswith('**') and line.endswith('**') and ':' not in line:
                            continue
                        
                        # Remove markdown bold **text**
                        line = re.sub(r'\*\*(.+?)\*\*', r'\1', line)
                        
                        # Handle numbered lists: "1. Title: Description"
                        if line and line[0].isdigit() and '. ' in line[:5]:
                            line = line.split('. ', 1)[1].strip()
                        
                        # Handle bullet points
                        if line.startswith(('- ', '* ', '• ')):
                            line = line[2:].strip()
                        
                        # Only accept lines with reasonable length
                        if len(line) > 15:
                            new_prompts.append(line)
                else:
                    logger.warning("Text content extracted from response is empty.")
            else:
                logger.warning("LLM response content is None.")
        except Exception as e:
            logger.error(f"Exception during extraction: {e}", exc_info=True)
        
        logger.info(f"Successfully generated {len(new_prompts)} new prompts")
        return new_prompts[:count_needed]
    except Exception as e:
        logger.error(f"Failed to generate prompts: {e}")
        return []
