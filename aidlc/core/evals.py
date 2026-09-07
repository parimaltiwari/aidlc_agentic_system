"""Deterministic and judge-backed phase evaluation."""

from statistics import mean

from aidlc.core.agent import BaseAgent
from aidlc.core.artifacts import EvalScorecard
from aidlc.core.state import AidlcState


class Evaluator(BaseAgent[EvalScorecard]):
    output_schema = EvalScorecard
    tier = "strong"
    threshold = 0.7
    rubric = ("quality", "coverage")

    def build_user_prompt(self, state: AidlcState) -> str:
        return f"Evaluate phase {self.phase}. Artifacts: {self.artifacts_json(state)}"

    def deterministic_checks(self, state: AidlcState) -> dict[str, float]:
        return {item: 1.0 for item in self.rubric}

    def as_node(self):
        def node(state: AidlcState) -> dict:
            result = self.run(state)
            from aidlc.core.store import ArtifactStore

            ArtifactStore(state.get("run_id", "local")).save(self.output_key, result)
            return {
                "artifacts": {self.output_key: result.model_dump(mode="json")},
                "scorecards": [result.model_dump(mode="json")],
                "log": [f"{self.phase}:{self.name} produced scorecard"],
                "phase": self.phase,
            }

        return node

    def run(self, state: AidlcState) -> EvalScorecard:
        deterministic = self.deterministic_checks(state)
        judge = super().run(state)
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

    def deterministic_checks(self, state: AidlcState) -> dict[str, float]:
        reqs = state.get("artifacts", {}).get("requirements_spec", {}).get("requirements", [])
        valid = bool(reqs) and len({r["id"] for r in reqs}) == len(reqs)
        criteria = all(r.get("acceptance_criteria") for r in reqs) if reqs else False
        return {"completeness": float(valid), "testability": float(criteria)}


class DesignEvaluator(Evaluator):
    name = "design-evaluator"
    phase = "design"

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
        return {"implementation": float(ok), "review": float(ok)}


class TestEvalEvaluator(Evaluator):
    name = "test-eval-evaluator"
    phase = "test_eval"

    def deterministic_checks(self, state: AidlcState) -> dict[str, float]:
        quality = state.get("artifacts", {}).get("quality_report", {})
        coverage = quality.get("coverage_by_requirement", {})
        return {
            "quality": float(quality.get("go", False)),
            "coverage": float(bool(coverage) and all(coverage.values())),
        }


class DeployEvaluator(Evaluator):
    name = "deploy-evaluator"
    phase = "deploy"

    def deterministic_checks(self, state: AidlcState) -> dict[str, float]:
        artifacts = state.get("artifacts", {})
        return {
            "deployment": float(artifacts.get("deploy_log", {}).get("healthy", False)),
            "soak": float(artifacts.get("soak_report", {}).get("healthy", False)),
        }
