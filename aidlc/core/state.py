"""LangGraph state and reducers."""

import operator
from typing import Annotated, TypedDict


def merge_dicts(left: dict, right: dict) -> dict:
    return {**left, **right}


class AidlcState(TypedDict, total=False):
    run_id: str
    intent: str
    context: dict
    phase: str
    artifacts: Annotated[dict[str, dict], merge_dicts]
    scorecards: Annotated[list, operator.add]
    gate_decisions: Annotated[list, operator.add]
    change_requests: list
    retries: dict[str, int]
    log: Annotated[list[str], operator.add]
    status: str
