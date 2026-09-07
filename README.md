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

## Layout

`core/` contains models, state, providers, gates, storage, and tracing;
`agents/` contains phase specialists; `orchestrators/` contains phase graphs and
the master FSM; `tools/` contains sandbox/git/static/test helpers; and
`services/` contains the FastAPI API.
