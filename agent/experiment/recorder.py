import csv
import logging
from pathlib import Path
from typing import Dict, Any, List
import datetime

logger = logging.getLogger("experiment_runner")

class ExperimentRecorder:
    FIELDNAMES = [
        "prompt_id", "config", "app_name", "start_time", "end_time", "gen_time", 
        "build_status", "gemini_input_tokens", "gemini_output_tokens", "gemini_total_tokens", 
        "gemini_api_calls", "anthropic_input_tokens", "anthropic_output_tokens", "anthropic_total_tokens", 
        "anthropic_api_calls", "total_api_calls", "user_prompt"
    ]

    def __init__(self, metrics_file: Path):
        self.metrics_file = metrics_file
        self._ensure_file()
        self.prompt_to_id = self._load_existing_ids()
        self.next_prompt_id = max([0] + list(self.prompt_to_id.values())) + 1

    def _ensure_file(self):
        if not self.metrics_file.exists():
            with open(self.metrics_file, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writeheader()

    def _load_existing_ids(self) -> Dict[str, int]:
        ids = {}
        if not self.metrics_file.exists():
            return ids
            
        try:
            with open(self.metrics_file, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        pid = row.get("prompt_id", "")
                        # Handle legacy IDs with dots
                        if "." in str(pid):
                            base_id = int(str(pid).split(".")[0])
                        else:
                            base_id = int(pid) if pid else 0
                        
                        text = row.get("user_prompt", "")
                        if text and base_id > 0:
                            ids[text] = base_id
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            logger.warning(f"Could not read existing IDs: {e}")
        return ids

    def get_prompt_id(self, prompt: str) -> int:
        if prompt in self.prompt_to_id:
            return self.prompt_to_id[prompt]
        
        pid = self.next_prompt_id
        self.prompt_to_id[prompt] = pid
        self.next_prompt_id += 1
        return pid

    def record_result(self, row: Dict[str, Any]):
        try:
            with open(self.metrics_file, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writerow(row)
                logger.info(f"Recorded metrics for {row.get('app_name', 'unknown')}")
        except Exception as e:
            logger.error(f"Failed to record result: {e}")

    @staticmethod
    def format_duration(seconds: float) -> str:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}min {s}sec"
