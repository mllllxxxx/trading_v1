# Brief: AI Berkshire Advisory Layer

## Request

Study `xbtlin/ai-berkshire` and design it as a feature inside Trade_V1.

## Classification

- Type: New initiative
- Lane: high-risk
- Reason: touches trading logic, LLM prompts, external research workflow, and future live-trading risk.

## Goal

Add AI Berkshire as a research/advisory layer for Trade_V1. It should improve
decision discipline, anti-bias checks, catalyst attribution, thesis tracking,
and portfolio exposure review without becoming an execution engine.

## Non-Goal

Do not import AI Berkshire as a direct order placer. Its output may reduce risk
or add cautionary context, but OKX execution must remain behind scheduler gates,
LLM decision parsing, validator hard rules, and bracket validation.

