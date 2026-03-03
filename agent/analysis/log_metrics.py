import re
import sys
import os
from datetime import datetime
from pathlib import Path # Added import for Path

def format_duration(seconds):
    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    return f"{minutes} minutes and {remaining_seconds:.2f} seconds"

def get_provider_from_model(model_name):
    """Determine provider from model name"""
    if not model_name:
        return None
    model_lower = model_name.lower()
    if "sonnet" in model_lower or "haiku" in model_lower or "claude" in model_lower:
        return "claude"
    elif "gemini" in model_lower:
        return "gemini"
    elif any(x in model_lower for x in ["llama", "mistral", "phi", "qwen", "ollama"]):
        return "ollama"
    return None

def read_env_coding_model(log_filename):
    """Try to read LLM_BEST_CODING_MODEL from .env file in the same directory structure"""
    try:
        # Log file is in logs_summary/, .env is in parent (agent/)
        log_path = Path(log_filename)
        if "logs_summary" in str(log_path):
            env_path = log_path.parent.parent / ".env"
        else:
            # Fallback: look for .env in parent directories
            env_path = log_path.parent / ".env"
            if not env_path.exists():
                env_path = log_path.parent.parent / ".env"
        
        if env_path.exists():
            with open(env_path, "r") as f:
                for line in f:
                    if line.strip().startswith("LLM_BEST_CODING_MODEL="):
                        value = line.split("=", 1)[1].strip()
                        # Remove comments
                        if "#" in value:
                            value = value.split("#")[0].strip()
                        return value
    except Exception:
        pass
    return None

def calculate_metrics(log_filename):
    if not os.path.isfile(log_filename):
        print(f"❌ Error: File '{log_filename}' not found.")
        return None
    
    # Try to determine coding model from .env
    env_coding_model = read_env_coding_model(log_filename)
    env_coding_provider = get_provider_from_model(env_coding_model) if env_coding_model else None

    # Totals for tokens and durations
    entries = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_tokens = 0
    total_duration = 0.0

    # Per-LLM tracking
    llm_stats = {
        "claude": {"entries": 0, "input": 0, "output": 0, "total": 0},
        "gemini": {"entries": 0, "input": 0, "output": 0, "total": 0},
    }

    # Regex for Anthropic/Gemini format
    api_pattern = re.compile(
        r"Input tokens: (\d+) \| Output tokens: (\d+) \| Total tokens: (\d+) \| Duration: ([\d.]+)s",
        re.IGNORECASE
    )
    
    # Regex for Ollama format (extracts from raw response logs)
    ollama_pattern = re.compile(
        r"prompt_eval_count=(\d+).*?eval_count=(\d+).*?total_duration=(\d+)",
        re.DOTALL
    )
    
    # Regex for Node token count (e.g., "LLM response token count (node 1): 617")
    node_token_pattern = re.compile(r"LLM response token count \(node \d+\): (\d+)")
    
    # Regex for "Total tokens consumed" summary lines
    total_consumed_pattern = re.compile(r"Total tokens consumed: (\d+)")
    
    # Regex to detect backend/provider
    backend_pattern = re.compile(r"Auto-detected backend: (\w+)")
    
    # Regex to capture timestamps in format: 2025-07-22 15:26:17
    timestamp_pattern = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

    first_timestamp = None
    last_timestamp = None
    current_backend = None  # Track the current backend context
    coding_backend = None  # Track the backend used for coding (NiceguiActor)
    in_code_generation = False  # Track if we're currently in code generation phase

    with open(log_filename, "r") as f:
        for line in f:
            # Update first and last timestamps for elapsed wall clock time
            ts_match = timestamp_pattern.search(line)
            if ts_match:
                current_ts = datetime.strptime(ts_match.group(1), "%Y-%m-%d %H:%M:%S")
                if not first_timestamp:
                    first_timestamp = current_ts
                last_timestamp = current_ts  # update as we progress through file
            
            # Detect backend changes
            backend_match = backend_pattern.search(line)
            if backend_match:
                detected = backend_match.group(1).lower()
                if detected == "anthropic":
                    current_backend = "claude"
                elif detected == "gemini":
                    current_backend = "gemini"
                elif detected == "ollama":
                    current_backend = "ollama"
                
                # Check if this backend is for the NiceguiActor (coding)
                # Look ahead in the line for "Initialized NiceguiActor"
                continue
            
            # Detect NiceguiActor initialization - this locks in the coding backend AND starts code gen phase
            # Prefer env_coding_provider (from .env file) over auto-detected backend
            if "Initialized NiceguiActor" in line:
                if env_coding_provider:
                    coding_backend = env_coding_provider
                elif current_backend:
                    coding_backend = current_backend
                in_code_generation = True  # We're now in code generation phase
                continue
            
            # Detect completion messages (but don't exit code gen yet - there may be multiple phases)
            # We stay in code generation until we see the final "Generation completed" message
            if "Generation completed in" in line:
                in_code_generation = False
                continue

            # Try to extract Anthropic/Gemini API format
            api_match = api_pattern.search(line)
            if api_match:
                input_tokens = int(api_match.group(1))
                output_tokens = int(api_match.group(2))
                tokens = int(api_match.group(3))
                duration = float(api_match.group(4))

                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                total_tokens += tokens
                total_duration += duration
                entries += 1

                # Identify LLM - prefer current_backend, fallback to line content
                if current_backend:
                    llm = current_backend
                else:
                    lower_line = line.lower()
                    if "claude" in lower_line or "anthropic" in lower_line:
                        llm = "claude"
                    elif "gemini" in lower_line:
                        llm = "gemini"
                    else:
                        continue

                llm_stats[llm]["entries"] += 1
                llm_stats[llm]["input"] += input_tokens
                llm_stats[llm]["output"] += output_tokens
                llm_stats[llm]["total"] += tokens
                continue

            # Try to extract Ollama format
            ollama_match = ollama_pattern.search(line)
            if ollama_match:
                input_tokens = int(ollama_match.group(1))
                output_tokens = int(ollama_match.group(2))
                duration_ns = int(ollama_match.group(3))
                duration = duration_ns / 1_000_000_000  # Convert nanoseconds to seconds
                tokens = input_tokens + output_tokens

                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                total_tokens += tokens
                total_duration += duration
                entries += 1

                # Ollama logs - identify model
                lower_line = line.lower()
                if "ollama" in lower_line or "llama" in lower_line or "mistral" in lower_line or "phi" in lower_line:
                    # Track Ollama under a separate category or you can map to existing
                    # For now, let's add it as a third category
                    if "ollama" not in llm_stats:
                        llm_stats["ollama"] = {"entries": 0, "input": 0, "output": 0, "total": 0}
                    
                    llm_stats["ollama"]["entries"] += 1
                    llm_stats["ollama"]["input"] += input_tokens
                    llm_stats["ollama"]["output"] += output_tokens
                    llm_stats["ollama"]["total"] += tokens
                continue

            # Try to extract Node token count - attribute based on context
            node_token_match = node_token_pattern.search(line)
            if node_token_match:
                tokens = int(node_token_match.group(1))
                total_tokens += tokens
                entries += 1
                
                # Choose backend based on whether we're in code generation or not
                if in_code_generation and coding_backend:
                    # During code generation, use coding_backend (Claude/Sonnet)
                    backend_to_use = coding_backend
                else:
                    # Outside code generation, use current_backend (Gemini for orchestration)
                    backend_to_use = current_backend
                
                if backend_to_use and backend_to_use in ["claude", "gemini", "ollama"]:
                    llm_stats[backend_to_use]["total"] += tokens
                    llm_stats[backend_to_use]["entries"] += 1
                else:
                    # Fallback to unknown category
                    if "unknown" not in llm_stats:
                        llm_stats["unknown"] = {"entries": 0, "input": 0, "output": 0, "total": 0}
                    llm_stats["unknown"]["total"] += tokens
                    llm_stats["unknown"]["entries"] += 1
                continue
            
            # Try to extract "Total tokens consumed" lines - also attribute to current backend
            total_consumed_match = total_consumed_pattern.search(line)
            if total_consumed_match:
                tokens = int(total_consumed_match.group(1))
                # Don't add to total_tokens (it would double-count with node tokens)
                # Just ensure it's attributed if we haven't seen node tokens
                if current_backend and current_backend in ["claude", "gemini", "ollama"]:
                    # This is a summary line, attribution was likely already done via node tokens
                    pass
                continue

    if entries == 0:
        return None

    # Calculate averages for tokens per time
    avg_tokens_per_sec = total_tokens / total_duration if total_duration else 0
    avg_tokens_per_min = avg_tokens_per_sec * 60
    
    elapsed_seconds = 0
    if first_timestamp and last_timestamp:
        elapsed = last_timestamp - first_timestamp
        elapsed_seconds = elapsed.total_seconds()

    return {
        "entries": entries,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_tokens": total_tokens,
        "total_duration": total_duration,
        "avg_tokens_per_sec": avg_tokens_per_sec,
        "avg_tokens_per_min": avg_tokens_per_min,
        "elapsed_seconds": elapsed_seconds,
        "llm_stats": llm_stats
    }

def main():
    if len(sys.argv) < 2:
        print("Usage: python log.py <log_filename>")
        sys.exit(1)

    log_filename = sys.argv[1]
    metrics = calculate_metrics(log_filename)
    
    if metrics is None:
        print("⚠️ No valid log entries found.")
        sys.exit(0)

    print(f"\n📊 Overall LLM Usage Summary")
    print(f"Total Entries: {metrics['entries']}")
    print(f"Total Input Tokens: {metrics['total_input_tokens']}")
    print(f"Total Output Tokens: {metrics['total_output_tokens']}")
    print(f"Total Tokens: {metrics['total_tokens']}")
    print(f"Total Duration (sum of processing times): {format_duration(metrics['total_duration'])}")
    print(f"Average Tokens per Second: {metrics['avg_tokens_per_sec']:.2f}")
    print(f"Average Tokens per Minute: {metrics['avg_tokens_per_min']:.2f}")

    for llm in ["claude", "gemini"]:
        stats = metrics['llm_stats'][llm]
        print(f"\n🔍 {llm.capitalize()} Stats:")
        print(f"Total Entries to {llm.capitalize()}: {stats['entries']}")
        print(f"Total Input Tokens for {llm.capitalize()}: {stats['input']}")
        print(f"Total Output Tokens for {llm.capitalize()}: {stats['output']}")
        print(f"Total Tokens for {llm.capitalize()}: {stats['total']}")

    # Calculate and print elapsed wall clock time between first and last timestamp
    if metrics['elapsed_seconds'] > 0:
        print(f"\n⏳ Elapsed wall clock time between first and last log timestamp:")
        print(f"{format_duration(metrics['elapsed_seconds'])}")
    else:
        print("\n⚠️ Could not find valid timestamps for elapsed time calculation.")

if __name__ == "__main__":
    main()
