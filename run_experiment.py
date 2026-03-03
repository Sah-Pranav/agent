#!/usr/bin/env python3
"""
Experiment Runner Entry Point

This script runs the automated experiment orchestration system.
It loads prompts, generates new ones if needed, and executes app generation
experiments using different LLM configurations.

Usage:
    uv run run_experiment.py
"""
import asyncio
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

from agent.experiment.runner import main

if __name__ == "__main__":
    asyncio.run(main())
