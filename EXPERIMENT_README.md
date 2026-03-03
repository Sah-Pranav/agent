# Experiment Runner & Automated Orchestration

This module provides a production-grade automated system for running batch experiments to generate web applications using different LLM configurations.

## 🏗 Architecture (Production Structure)

The logic is distributed across specialized modules within the `agent/` package:

- **`run_experiment.py`**: The main entry point script.
- **`agent/experiment/runner.py`**: The Orchestrator that manages the end-to-end experiment lifecycle.
- **`agent/experiment/recorder.py`**: Handles result persistence and CSV metrics generation.
- **`agent/core/config.py`**: Centralized configuration and environment management.
- **`agent/core/docker_utils.py`**: Infrastructure utilities for Docker Desktop and Docker Compose.
- **`agent/llm/prompt_factory.py`**: Logic for loading and auto-generating experimental prompts.
- **`agent/analysis/log_metrics.py`**: Parser for extracting token usage and performance metrics from execution logs.

## 🚀 Getting Started

### Prerequisites
- macOS (for auto-start features of Docker/Ollama)
- Docker Desktop installed
- Ollama installed (for local prompt generation)

### Running Experiments
1. **Configure**: Update `config.yaml` with your target models and prompt settings.
2. **Launch**:
   ```bash
   uv run run_experiment.py
   ```
3. **Review**: Check the experiment plan in the console and type `y` to proceed.

## 📊 Results & Monitoring
- **Metrics**: Detailed performance data is saved to `metrics_summary.csv`.
- **Logs**: Execution logs are stored in `logs_summary/`.
- **Apps**: Generated applications are stored in `generated_apps/`.

## 🛠 Maintenance
- To change how results are saved, modify `agent/experiment/recorder.py`.
- To add new LLM providers for prompts, modify `agent/llm/prompt_factory.py`.
- To update Docker cleanup/setup logic, modify `agent/core/docker_utils.py`.
