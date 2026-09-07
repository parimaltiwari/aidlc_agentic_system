# AIDLC

AIDLC is a deterministic, multi-agent AI-driven development lifecycle built on
LangGraph. It moves an intent through Requirements → Design → Build → Test & Eval
→ Deploy, preserving typed artifacts, evaluation scorecards, approval gates, and
traceability. Mock mode performs a complete offline run; LiteLLM is pluggable.

```text
Ticket / PRD → Master FSM → [Requirements → Design → Build → Test/Eval → Deploy]
                    ↘ typed artifact store, gates, evals, tracing, sandbox
```

## Quickstart

```bash
uv sync
uv run aidlc run "Add password reset via email to the user service" --auto-approve
```

Useful environment variables: `AIDLC_LLM_PROVIDER=mock|litellm`,
`AIDLC_MODEL`, `AIDLC_MODEL_STRONG`, `AIDLC_AUTO_APPROVE=1`, and
`AIDLC_RUNS_DIR=./runs`. To use a real provider, set the appropriate LiteLLM
credentials and run with `--provider litellm`.

`AIDLC_MODEL` is used by fast agents and `AIDLC_MODEL_STRONG` by evaluators.
`AIDLC_AUTO_APPROVE=1` bypasses review interruptions; without it, high-risk
runs pause at each human gate. Checkpoints are stored in
`$AIDLC_RUNS_DIR/checkpoints.sqlite`.

## Approval

Start a high-risk run without auto-approval:

```bash
uv run aidlc run "Add password reset" --risk high
uv run aidlc approve RUN_ID --by parimal
uv run aidlc approve RUN_ID --by parimal --reject
```

The API provides the same durable flow:

```bash
curl -X POST http://127.0.0.1:8000/runs/RUN_ID/approve \
  -H 'content-type: application/json' \
  -d '{"approved": true, "by": "parimal"}'
```

## Master routing

After each phase gate, a block ends the run with `blocked`. A failed scorecard
is retried up to two times, with evaluator feedback recorded in the run log.
Test/evaluation triage can create a backward `ChangeRequest` to Design or
Build, with at most two backward hops. Otherwise the next lifecycle phase is
run; only an approved Deploy gate produces `completed`.

## Layout

`core/` contains models, state, providers, gates, storage, and tracing;
`agents/` contains phase specialists; `orchestrators/` contains phase graphs and
the master FSM; `tools/` contains sandbox/git/static/test helpers; and
`services/` contains the FastAPI API.

## Run with a local open-source model (Ollama)

Install Ollama and start its local server:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
```

Pull the fast and strong models in another terminal:

```bash
ollama pull qwen2.5:3b
ollama pull qwen2.5:7b
```

Run the lifecycle without API keys. The Ollama provider uses
`qwen2.5:3b` for fast agents and `qwen2.5:7b` for evaluator agents by default:

```bash
AIDLC_AUTO_APPROVE=1 uv run aidlc run \
  "Add password reset via email to the user service" \
  --provider ollama --auto-approve --verbose
```

Override the models or server when needed:

```bash
AIDLC_MODEL=qwen2.5:3b \
AIDLC_MODEL_STRONG=qwen2.5:7b \
OLLAMA_BASE_URL=http://127.0.0.1:11434 \
uv run aidlc run "Add password reset" --provider ollama --auto-approve
```

**Performance notes.** On this 8-CPU, no-GPU machine, observed per-call
latencies were approximately 3–82 seconds for `qwen2.5:3b` (with one
153-second outlier), and 3–78 seconds for `qwen2.5:7b` (with a measured
153-second outlier). A `qwen2.5-coder:1.5b` run was started and measured
approximately 1–158 seconds per call during Requirements/Design, but was
stopped before completion. For production-scale runs, use a GPU or a hosted
open-model endpoint such as vLLM, Together, or Groq via `--provider litellm`,
for example `AIDLC_MODEL=groq/llama-3.1-70b-versatile`.
