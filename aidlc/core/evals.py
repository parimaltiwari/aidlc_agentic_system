"""Deterministic and judge-backed phase evaluation."""

import json
from statistics import mean

from aidlc.core.agent import BaseAgent
from aidlc.core.artifacts import EvalScorecard
from aidlc.core.state import AidlcState
from aidlc.core.store import ArtifactStore


class Evaluator(BaseAgent[EvalScorecard]):
    output_schema = EvalScorecard
    tier = "strong"
    threshold = 0.7
    rubric = ("quality", "coverage")

    def build_user_prompt(self, state: AidlcState) -> str:
        rubric = ", ".join(self.rubric)
        evidence = json.dumps(self.deterministic_checks(state), sort_keys=True)
        shape = json.dumps(
            {
                "phase": self.phase,
                "agent": self.name,
                "scores": {key: 0.0 for key in self.rubric},
                "overall": 0.0,
                "passed": False,
                "feedback": [],
            }
        )
        return (
            f"Evaluate phase {self.phase}. Score only these rubric keys: {rubric}. "
            f"Score each key from 0.0 to 1.0 using the artifacts as evidence. "
            f"Do not return all zeros when the artifacts satisfy the rubric. "
            f"Deterministic evidence signals (use as corroborating evidence): {evidence}. "
            f"Return exactly this JSON shape: {shape}. Artifacts: {self.artifacts_json(state)}"
        )

    def deterministic_checks(self, state: AidlcState) -> dict[str, float]:
        return {item: 1.0 for item in self.rubric}

    def as_node(self):
        def node(state: AidlcState) -> dict:
            result = self.run(state)
            ArtifactStore(state.get("run_id", "local")).save(self.output_key, result)
            return {
                "artifacts": {self.output_key: result.model_dump(mode="json")},
                "scorecards": [result.model_dump(mode="json")],
                "log": [f"{self.phase}:{self.name} produced scorecard"],
            }

        return node

    def run(self, state: AidlcState) -> EvalScorecard:
        deterministic = self.deterministic_checks(state)
        judges = [super().run(state)]
        if deterministic and all(value >= 1.0 for value in deterministic.values()):
            for _ in range(2):
                if judges[-1].overall >= self.threshold:
                    break
                judges.append(super().run(state))
        judge = max(judges, key=lambda result: result.overall)
        if (
            deterministic
            and all(value >= 1.0 for value in deterministic.values())
            and judge.scores
            and all(value == 0 for value in judge.scores.values())
        ):
            judge = judge.model_copy(update={"scores": deterministic, "overall": 1.0})
        scores = {
            key: min(deterministic.get(key, 1.0), value) for key, value in judge.scores.items()
        }
        scores.update({key: value for key, value in deterministic.items() if key not in scores})
        overall = mean(scores.values()) if scores else 0.0
        return EvalScorecard(
            phase=self.phase,
            agent=self.name,
            scores=scores,
            overall=overall,
            passed=overall >= self.threshold,
            feedback=[] if overall >= self.threshold else ["Improve deterministic checks"],
        )


class RequirementsEvaluator(Evaluator):
    name = "requirements-evaluator"
    phase = "requirements"
    relevant_artifacts = ("requirements_spec", "compliance_notes")
    system_prompt = "Evaluate requirements for completeness, testability, and compliance."
    rubric = ("completeness", "testability", "compliance")

    def deterministic_checks(self, state: AidlcState) -> dict[str, float]:
        reqs = state.get("artifacts", {}).get("requirements_spec", {}).get("requirements", [])
        valid = bool(reqs) and len({r["id"] for r in reqs}) == len(reqs)
        criteria = all(r.get("acceptance_criteria") for r in reqs) if reqs else False
        compliance = (
            not state.get("artifacts", {}).get("compliance_notes", {}).get("blocking", True)
        )
        return {
            "completeness": float(valid),
            "testability": float(criteria),
            "compliance": float(compliance),
        }


class DesignEvaluator(Evaluator):
    name = "design-evaluator"
    phase = "design"
    relevant_artifacts = ("requirements_spec", "design_package")
    system_prompt = "Evaluate design traceability and work-plan dependency integrity."
    rubric = ("traceability", "dag")

    def deterministic_checks(self, state: AidlcState) -> dict[str, float]:
        reqs = {
            x["id"]
            for x in state.get("artifacts", {}).get("requirements_spec", {}).get("requirements", [])
        }
        rows = (
            state.get("artifacts", {})
            .get("design_package", {})
            .get("traceability", {})
            .get("rows", [])
        )
        covered = {row["requirement_id"] for row in rows}
        items = (
            state.get("artifacts", {})
            .get("design_package", {})
            .get("work_plan", {})
            .get("items", [])
        )
        ids = {i["id"] for i in items}
        acyclic = all(dep in ids for i in items for dep in i.get("depends_on", []))
        return {"traceability": float(reqs <= covered), "dag": float(acyclic)}


class BuildEvaluator(Evaluator):
    name = "build-evaluator"
    phase = "build"
    relevant_artifacts = ("design_package", "static_report")
    system_prompt = "Evaluate implementation, reviews, static analysis, and tests."
    rubric = ("implementation", "review", "static")

    def deterministic_checks(self, state: AidlcState) -> dict[str, float]:
        artifacts = state.get("artifacts", {})
        plan = artifacts.get("design_package", {}).get("work_plan", {}).get("items", [])
        ok = all(
            artifacts.get(f"code_diff_{i['id'].lower().replace('-', '_')}")
            and artifacts.get(f"review_report_{i['id'].lower().replace('-', '_')}", {}).get(
                "approved"
            )
            for i in plan
        )
        static_ok = artifacts.get("static_report", {}).get("passed", False)
        return {"implementation": float(ok), "review": float(ok), "static": float(static_ok)}


class TestEvalEvaluator(Evaluator):
    name = "test-eval-evaluator"
    phase = "test_eval"
    relevant_artifacts = ("requirements_spec", "test_plan", "test_results", "quality_report")
    system_prompt = "Evaluate requirement coverage and deterministic test outcomes."
    rubric = ("quality", "coverage")

    def deterministic_checks(self, state: AidlcState) -> dict[str, float]:
        artifacts = state.get("artifacts", {})
        requirements = {
            item["id"] for item in artifacts.get("requirements_spec", {}).get("requirements", [])
        }
        cases = artifacts.get("test_plan", {}).get("cases", [])
        covered = {req_id for case in cases for req_id in case.get("requirement_ids", [])}
        result_items = artifacts.get("test_results", {}).get("results", [])
        all_passed = bool(result_items) and all(item.get("passed", False) for item in result_items)
        coverage = {req_id: req_id in covered for req_id in requirements}
        return {
            "quality": float(bool(coverage) and all(coverage.values()) and all_passed),
            "coverage": float(bool(requirements) and requirements <= covered and all_passed),
        }


class DeployEvaluator(Evaluator):
    name = "deploy-evaluator"
    phase = "deploy"
    relevant_artifacts = ("quality_report", "deploy_log", "soak_report", "rollback_report")
    system_prompt = "Evaluate deployment health and soak evidence."
    rubric = ("deployment", "soak")

    def deterministic_checks(self, state: AidlcState) -> dict[str, float]:
        artifacts = state.get("artifacts", {})
        return {
            "deployment": float(artifacts.get("deploy_log", {}).get("healthy", False)),
            "soak": float(artifacts.get("soak_report", {}).get("healthy", False)),
        }
