# Evaluation for the Agentic Full-Stack Generative AI Frameworks in Preproduction Testing

> **Author**: Pranav Kumar Sah | Master's Thesis, 2025–2026  
> **University**: Technical University of Applied Sciences Würzburg-Schweinfurt (THWS)  
> **Research Collaboration**: [Databricks app.build team](https://www.databricks.com/research?search=framework#publications)  
> **Published Paper**: [arXiv:2509.03310](https://arxiv.org/abs/2509.03310)

---

## About This Repository

This is a **research fork** of [appdotbuild/agent](https://www.app.build) — an open-source agentic framework that generates production-ready full-stack web applications from a single natural language prompt.

This fork was created as part of a Master's thesis — conducted in collaboration with the **Databricks app.build team** — researching the **evaluation of agentic full-stack Generative AI frameworks in preproduction testing**. The core contribution is a fully automated ablation study pipeline that measures the impact of different validation layers on agent reliability and computational cost.

**Research Question:**
> *How do individual preproduction validation checks (Linting, Type-Checking, Unit Testing, SQLModel) affect the reliability and efficiency of an agentic full-stack code generation system?*

---

## What the Original Repository Had

The upstream [app.build](https://github.com/neondatabase/appdotbuild-agent/tree/main/agent) framework provides:

- **`NiceguiActor`** — an LLM-powered code generation agent using Beam Search (`beam_width=3`, `max_depth=30`)
- **Validation Pipeline** — four independent checks run inside a sandboxed environment:
  - `ruff` for Linting
  - `pyright` for Type Checking
  - `pytest` for Unit Tests
  - `pytest -m sqlmodel` for DB Smoke Tests
- **Docker Sandboxing** — each generated app runs in an ephemeral Docker container
- **Interactive UI** — a Streamlit/SSE interface for manual use

---

## My Contributions (This Branch)

This branch (`automate-thesis-tasks`) adds a **headless experiment orchestration layer** on top of the base framework. For each prompt × configuration pair, the pipeline:

1. **Generates** the full-stack application using the agentic core
2. **Saves** the source code to `generated_apps/<app_name>_<config>/`
3. **Builds and deploys** the app as a Docker container automatically
4. **Prevents conflicts** — each run uses a project-specific container name, so multiple experiments can run without port or naming collisions
5. **Saves per-app logs** — full execution logs written to `logs_summary/<app_name>_<config>.log` for debugging and reproducibility
6. **Logs metrics** — token usage, latency, and pass/fail status are written to `metrics_summary.csv`

| New File | Purpose |
|:---|:---|
| `run_experiment.py` | Entry point — runs the full batch experiment suite |
| `agent/experiment/runner.py` | Orchestration engine — iterates prompts × configs, saves apps, deploys Docker |
| `agent/experiment/recorder.py` | Persists results to `metrics_summary.csv` |
| `agent/analysis/log_metrics.py` | Parses execution logs for token and latency data |
| `config.yaml` | Defines ablation configurations (which checks to skip) |
| `prompts.txt` | Standardized prompt dataset for reproducible experiments |
| `metrics_summary.csv` | Output: experimental results across all runs |

---

## Navigating the Repository

```
agent/
├── run_experiment.py           ← START HERE to run experiments
├── config.yaml                 ← Configure ablation settings & prompt count
├── prompts.txt                 ← Add/edit your prompt dataset
├── metrics_summary.csv         ← Experiment results output
├── .env.example                ← Template for environment variables
├── .env                        ← Your local config (copy from .env.example, not committed)
│
├── agent/experiment/
│   ├── runner.py               ← Core orchestration logic
│   └── recorder.py             ← CSV metrics writer
│
├── agent/analysis/
│   └── log_metrics.py          ← Log parser (tokens, latency)
│
└── agent/nicegui_agent/
    └── actors.py               ← NiceguiActor (Beam Search + validation)
```

---

## Getting Started

### Prerequisites
- Python 3.11+ with [`uv`](https://github.com/astral-sh/uv)
- Docker Desktop (running)
- Anthropic and Gemini API keys

### Setup

```bash
# Clone this fork and switch to the thesis branch
git clone https://github.com/Sah-Pranav/agent.git
cd agent
git checkout automate-thesis-tasks

# Set up environment
cp .env.example .env       # Fill in your API keys

# Install dependencies
uv sync

# Run the experiments
uv run run_experiment.py
```

### Ablation Configuration (`config.yaml`)

```yaml
# Auto-generate additional prompts using an LLM if prompts.txt has fewer entries
target_prompt_count: 30   # Total prompts to run; auto-generates missing ones via LLM if prompts.txt has fewer

configs:
  - name: all_checks_on
    settings: {}
  - name: lint_off
    settings:
      check_settings:
        skip_lint: true
  - name: type_check_off
    settings:
      check_settings:
        skip_type_check: true
```

> **`target_prompt_count`**: If `prompts.txt` contains fewer prompts than this number, the system automatically generates additional prompts using an LLM (Gemini or Ollama, configured in `.env`), extending the dataset without manual effort.

---

## Key Links

| Resource | Link |
|:---|:---|
| 📄 Published Paper | [arXiv:2509.03310](https://arxiv.org/abs/2509.03310) |
| 🔀 Upstream app.build | [appdotbuild/agent](https://github.com/appdotbuild/agent) |
| 🌿 This Thesis Branch | [Sah-Pranav/agent — automate-thesis-tasks](https://github.com/Sah-Pranav/agent/tree/automate-thesis-tasks) |

---