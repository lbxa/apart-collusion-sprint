# Inducing & Detecting Collusion in LLM Agents — Knockout Experiment

**Apart Research AI Collusion Sprint (Oct 2026)**

A Python experiment harness that tests whether LLM agents develop collusive
arrangements in a veracity dispute game, using a knockout experimental design
to identify which environmental levers are necessary for collusion to emerge.

## Quick Start

```bash
# Install dependency
pip install openai

# ── STEP 1: Verify everything works (no API key needed) ──
python run_demo.py --both
# Runs two scripted episodes:
#   --honest  : 7 honest jurors → correct verdict, no collusion
#   --collude : 4/7 rigged jurors → false verdict, collusion detected
# Produces markdown transcripts in results/demo/

# ── STEP 2: Run with LLM agents ──
export OPENROUTER_API_KEY=your_key_here

# Dry run (no API key needed — uses scripted agents)
python run_knockout.py --dry-run

# Pilot: full condition only (20 episodes)
python run_knockout.py --pilot

# Minimum viable: 5 key conditions
python run_knockout.py --minimum

# Full knockout: all 8 conditions
python run_knockout.py --full

# Analyze results
python analyze_results.py
```

## The Game

A **veracity dispute game** where:

1. **Creator** posts a claim and bets $10
2. **Challenger** evaluates and counter-bets $10
3. **Jury** (7 members) deliberates over 3 rounds, then votes
4. **Settlement**: winner gets bet back + 60% of loser's bet; jurors split 30%; protocol takes 10%
5. Jurors post a $1 bond (forfeited if they don't vote)

## Experimental Design

**Knockout design**: start with all 6 collusion-enabling levers active,
then remove one at a time to find which are necessary.

### 6 Levers

| Lever | Full | Knockout |
|-------|------|----------|
| Private channel | Coalition jurors can message privately | Public only |
| Side payments | Creator offers $2 bribes to jurors | No bribes |
| Repeated play | Agents remember past 10 episodes | No memory |
| High stakes | $10/$10 bets | $1/$1 bets |
| Ambiguous evidence | Hard-to-evaluate fictional claims | Clear-cut claims |
| No detection risk | No monitoring mentioned | Audit warning in prompts |

### 8 Conditions

| ID | Name | Levers Active |
|----|------|--------------|
| `knockout_full` | Full Collusion | 6/6 |
| `knockout_honest` | Honest Baseline | 2/6 |
| `knockout_no_channel` | KO: No Private Channel | 5/6 |
| `knockout_no_transfers` | KO: No Side Payments | 5/6 |
| `knockout_no_repeat` | KO: No Repeated Play | 5/6 |
| `knockout_low_stakes` | KO: Low Stakes | 5/6 |
| `knockout_clear_evidence` | KO: Clear Evidence | 5/6 |
| `knockout_detection` | KO: Detection Risk | 5/6 |

## Architecture

```
harness/
  run_demo.py              # ★ First thing to run — verifies everything works
  run_knockout.py          # Main entry point (CLI)
  run_experiments.py       # Original entry point (extended treatments)
  analyze_results.py       # Post-experiment analysis
  test_harness.py          # Integration tests (6 tests, all passing)
  requirements.txt

  game_api/
    types.py               # Core types: Phase, Verdict, PayoutConfig, Scenario, etc.
    interface.py            # Abstract GameAPI
    mock.py                 # In-process mock with full settlement math
    state_file.py           # Adapter for file-based game state

  agents/
    base.py                 # BaseAgent ABC + AgentConfig
    llm_agent.py            # LLM-backed agent (OpenRouter/OpenAI/Anthropic)
    scripted.py             # Scripted agents (Honest, Adversarial, Random, etc.)
    prompts.py              # Prompt templates for all roles and phases

  experiments/
    treatments.py           # TreatmentConfig + predefined treatments
    knockout.py             # 8-condition knockout design + fictional scenarios
    runner.py               # Experiment orchestrator (~560 lines)

  metrics/
    collector.py            # EpisodeRecord, ExperimentMetrics, MetricsCollector
    episode_logger.py       # ★ Markdown transcript with every handoff + money flow
    collusion_detector.py   # ★ 6-signal collusion detection (voting, bribes, etc.)

  scenarios/
    examples.py             # Factual, ambiguous, and attack scenarios
```

## LLM Configuration

Default model: **NVIDIA Nemotron 3 Ultra 550B** (`nvidia/nemotron-3-ultra-550b-a55b:free`) via OpenRouter.

Chosen for:
- **Free** on OpenRouter (no credits needed)
- Chain-of-thought reasoning (CoT `<think>` tags automatically captured for analysis)
- 550B parameter model with strong reasoning capability

To use a different model, pass overrides in `TreatmentConfig`:
```python
treatment = TreatmentConfig(
    creator_model="anthropic/claude-3.5-sonnet",
    creator_provider="openrouter",
    juror_model="openai/gpt-4o",
    juror_provider="openrouter",
    ...
)
```

## Output

Results go to `results/knockout/` (configurable with `--output`):

- `knockout_results.json` — aggregated per-condition metrics
- `exp_*/episodes.jsonl` — per-episode records with full detail
- `exp_*/summary.json` — per-experiment summary

After running `analyze_results.py`:
- `knockout_summary.csv` — CSV for further analysis
- `findings.md` — generated findings writeup

## Key Metrics

| Metric | What it measures |
|--------|-----------------|
| **False verdict rate** | % of episodes where jury verdict disagrees with ground truth |
| **Verdict accuracy** | % of episodes where jury got it right |
| **Hung jury rate** | % of episodes with no majority |
| **Completion rate** | % of episodes that reached settlement |
| **Attack success rate** | % of coalition episodes producing false verdicts |

## Testing

```bash
python test_harness.py
```

Runs 6 integration tests validating:
- Honest baseline (100% accuracy)
- Adversarial majority (false verdicts)
- Non-voter attack (hung juries + bond forfeiture)
- Settlement accounting ($10/$10 payout math)
- Deliberation messages (correct count and polling)
- Custom payout structures

## Extending

### Swap in a real game engine

Replace `MockGameAPI` with an adapter to the Rust runner or Solidity contracts:

```python
from game_api.interface import GameAPI

class RustGameAPI(GameAPI):
    async def register_episode(self, config, creator_id, ...):
        # Call the Rust binary
        ...
```

### Add new conditions

Add a `TreatmentConfig` to `experiments/knockout.py` and register it in
`KNOCKOUT_CONDITIONS`.

### Add new scenarios

Add `Scenario` objects to `scenarios/examples.py` or
`experiments/knockout.py`.