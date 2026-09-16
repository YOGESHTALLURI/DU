"""
Pipeline Compiler — Wave 0

Input:
  Feed metadata + FeedVersion configuration snapshot

Output:
  Generic, executable stage plan:
    1. LANDING
    2. BRONZE (Immutable source storage)
    3. SILVER_RAW (Schema validation, quarantine routing, lineage)

STRICT RULE:
  NO FEED-SPECIFIC CODE (e.g. no `if feed_id == 'FIDELIS': ...`).
  All transformation and validation rules are derived generically from
  the feed's published configuration snapshot.
"""
from typing import Dict, Any, List
from backend.models.feed import Feed, FeedVersion
from backend.models.pipeline import StageNameEnum, WAVE0_STAGE_ORDER


class StagePlan:
    def __init__(self, stage_name: StageNameEnum, order: int, config: Dict[str, Any]):
        self.stage_name = stage_name
        self.order = order
        self.config = config

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_name": self.stage_name.value,
            "order": self.order,
            "config": self.config,
        }


class PipelineExecutionPlan:
    def __init__(self, feed: Feed, version: FeedVersion, stages: List[StagePlan]):
        self.feed_id = feed.id
        self.feed_name = feed.name
        self.version_number = version.version_number
        self.stages = stages

    def get_stage_plan(self, stage_name: StageNameEnum) -> StagePlan | None:
        return next((s for s in self.stages if s.stage_name == stage_name), None)


class PipelineCompiler:
    """
    Compiles generic feed metadata into a deterministic stage execution plan.
    Zero feed-specific branching.
    """

    @classmethod
    def compile(cls, feed: Feed, version: FeedVersion) -> PipelineExecutionPlan:
        snapshot = version.config_snapshot or {}
        fields = snapshot.get("fields", [])
        delimiter = snapshot.get("delimiter", ",")
        has_header = snapshot.get("has_header", True)

        stages: List[StagePlan] = [
            # 1. LANDING Stage: file discovery and raw row counting
            StagePlan(
                stage_name=StageNameEnum.LANDING,
                order=1,
                config={
                    "landing_folder": feed.landing_folder,
                    "filename_pattern": feed.filename_pattern,
                    "format": feed.format.value,
                },
            ),
            # 2. BRONZE Stage: bit-for-bit immutable copy into data lake
            StagePlan(
                stage_name=StageNameEnum.BRONZE,
                order=2,
                config={
                    "preserve_raw": True,
                    "verify_checksum": True,
                    "target_subpath": f"bronze/{feed.name}",
                },
            ),
            # 3. SILVER_RAW Stage: parse, generic validation, lineage, quarantine
            StagePlan(
                stage_name=StageNameEnum.SILVER_RAW,
                order=3,
                config={
                    "delimiter": delimiter,
                    "has_header": has_header,
                    "fields": fields,
                    "target_subpath": f"silver_raw/{feed.name}",
                },
            ),
        ]

        
        # Wave 3: Identity and ODS Stages
        if snapshot.get("enable_identity") or getattr(feed, "domain", None) in ("IDENTITY", "PATIENT", "CLINICAL_IDENTITY", "MEMBERSHIP_IDENTITY") or snapshot.get("wave", 0) >= 3:
            stages.append(
                StagePlan(
                    stage_name=StageNameEnum.IDENTITY,
                    order=4,
                    config={
                        "domain": feed.domain,
                    },
                )
            )
        if snapshot.get("enable_ods") or snapshot.get("wave", 0) >= 3:
            stages.append(
                StagePlan(
                    stage_name=StageNameEnum.ODS,
                    order=5,
                    config={
                        "target_schema": "internal_ods",
                    },
                )
            )

        return PipelineExecutionPlan(feed=feed, version=version, stages=stages)
