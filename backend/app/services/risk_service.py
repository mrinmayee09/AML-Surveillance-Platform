"""Composite risk scoring and explanation.

A score is produced from two independent sources:

  1. the trained proactive model's probability, and
  2. the configurable rules engine's point total.

They are blended, and the resulting 0-100 score is then decomposed into factors
whose contributions SUM TO THE SCORE. That is what makes the "+22 / +18 / +15"
breakdown on the customer page trustworthy rather than decorative: the numbers
reconcile.

Where a rule and a model attribution describe the same underlying signal they are
merged into one factor, so an investigator does not see the same finding twice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ml.features import FEATURE_BY_NAME, FeatureBundle
from app.ml.model import Attribution, Prediction, ProactiveRiskModel, positive_attributions
from app.ml.registry import get_proactive_model
from app.models import Customer, RiskAssessment
from app.models.enums import AssessmentKind, RiskTrend
from app.rules.engine import RuleHit, rule_points
from app.schemas.common import ModelProvenance, RiskFactor

# Blend weights. The rules engine is a deliberate counterweight to the model:
# an institution must be able to reason about, and override, why a score moved.
MODEL_WEIGHT = 0.45
RULES_WEIGHT = 0.55

# Minimum points a factor must carry to be worth an investigator's attention
MIN_FACTOR_POINTS = 1.0

# The advisory shown next to every score in the product.
RISK_ADVISORY = (
    "A risk score is a prioritisation signal, not a finding of wrongdoing. It "
    "indicates that activity warrants human review under the institution's AML "
    "procedures. It does not establish that any offence occurred, and it must not "
    "be treated as evidence or communicated to the customer as an accusation."
)

# Maps a rule's feature onto the model feature describing the same signal, so the
# two sources can be merged into a single factor.
_RULE_FEATURE_ALIASES: Dict[str, str] = {
    "amount": "amount_log",
    "behaviour_drift": "amount_deviation_ratio",
}


@dataclass
class RiskResult:
    """Everything the platform knows about one scoring event."""

    score: float
    level: str
    decision: str
    trend: str
    factors: List[RiskFactor] = field(default_factory=list)
    features: Dict[str, float] = field(default_factory=dict)
    model_probability: Optional[float] = None
    rule_hits: List[RuleHit] = field(default_factory=list)
    provenance: Optional[ModelProvenance] = None
    advisory: str = RISK_ADVISORY

    @property
    def triggered_rule_codes(self) -> List[str]:
        return [hit.code for hit in self.rule_hits]

    def factor_dicts(self) -> List[Dict[str, Any]]:
        return [f.model_dump() for f in self.factors]


def _provenance_from(prediction: Prediction) -> ModelProvenance:
    data = prediction.provenance()
    return ModelProvenance(
        model_name=data["model_name"],
        model_version=data["model_version"],
        model_type=data["model_type"],
        trained=data["trained"],
        training_data=data["training_data"],
        notes=data["notes"],
    )


def _attribution_factor(attr: Attribution, points: float) -> RiskFactor:
    spec = FEATURE_BY_NAME.get(attr.feature)
    detail = f"Observed {attr.value_display}."
    if spec is not None:
        detail = f"Observed {attr.value_display} - {spec.description}"
    return RiskFactor(
        code=f"MODEL_{attr.feature.upper()}",
        label=attr.label,
        contribution=round(points, 1),
        detail=detail,
        category=attr.category,
    )


def build_factors(
    rule_hits: Sequence[RuleHit],
    attributions: Sequence[Attribution],
    model_points: float,
    final_score: float,
) -> List[RiskFactor]:
    """Decompose `final_score` into factors that sum back to it."""
    positives = positive_attributions(list(attributions))
    attribution_total = sum(a.delta for a in positives) or 1.0

    # --- Weighted, unnormalised candidate factors -------------------------
    # Keyed by the underlying signal so rules and attributions can merge.
    candidates: Dict[str, Dict[str, Any]] = {}

    for hit in rule_hits:
        signal = _RULE_FEATURE_ALIASES.get(hit.feature, hit.feature)
        candidates[signal] = {
            "code": hit.code,
            "label": hit.name,
            "detail": hit.explanation,
            "category": hit.category,
            "weight": RULES_WEIGHT * hit.contribution,
            "from_rule": True,
        }

    for attr in positives:
        share = (attr.delta / attribution_total) * model_points
        weight = MODEL_WEIGHT * share
        existing = candidates.get(attr.feature)
        if existing is not None:
            # Same signal found by both sources: keep the rule's precise wording
            # and note the model's agreement.
            existing["weight"] += weight
            existing["detail"] = (
                f"{existing['detail']} The model independently ranks this among the "
                "strongest contributors for this customer."
            )
            continue
        factor = _attribution_factor(attr, weight)
        candidates[attr.feature] = {
            "code": factor.code,
            "label": factor.label,
            "detail": factor.detail,
            "category": factor.category,
            "weight": weight,
            "from_rule": False,
        }

    if sum(c["weight"] for c in candidates.values()) <= 0:
        return []

    # --- Drop negligible factors, THEN rescale the survivors ---------------
    # Order matters: rescaling first and filtering second would leave the
    # displayed contributions summing to less than the score, which would make
    # the breakdown fail to reconcile. Dropping a factor can push others above
    # the threshold, so this repeats until the retained set is stable.
    retained = list(candidates.values())
    while retained:
        total_weight = sum(entry["weight"] for entry in retained)
        if total_weight <= 0:
            return []
        scale = final_score / total_weight
        survivors = [e for e in retained if e["weight"] * scale >= MIN_FACTOR_POINTS]
        if len(survivors) == len(retained):
            break
        if not survivors:
            # Everything is individually negligible: keep the single largest so
            # the score is never presented with no explanation at all.
            retained = [max(retained, key=lambda e: e["weight"])]
            break
        retained = survivors

    total_weight = sum(entry["weight"] for entry in retained) or 1.0
    scale = final_score / total_weight

    factors = [
        RiskFactor(
            code=entry["code"],
            label=entry["label"],
            contribution=round(entry["weight"] * scale, 1),
            detail=entry["detail"],
            category=entry["category"],
        )
        for entry in retained
    ]
    factors.sort(key=lambda f: f.contribution, reverse=True)

    # Push any residue from rounding onto the largest factor so the column
    # visibly adds up to the score an investigator is shown.
    residue = round(final_score - sum(f.contribution for f in factors), 1)
    if factors and abs(residue) >= 0.1:
        factors[0].contribution = round(factors[0].contribution + residue, 1)

    return factors


def determine_trend(
    db: Session, customer: Customer, new_score: float, lookback_days: int = 45
) -> str:
    """Compare against the customer's own recent history."""
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    previous: Sequence[RiskAssessment] = db.scalars(
        select(RiskAssessment)
        .where(
            RiskAssessment.customer_id == customer.id,
            RiskAssessment.kind == AssessmentKind.PROACTIVE.value,
            RiskAssessment.assessed_at >= cutoff,
        )
        .order_by(RiskAssessment.assessed_at.desc())
        .limit(6)
    ).all()

    if not previous:
        return RiskTrend.STABLE.value

    baseline = sum(a.risk_score for a in previous) / len(previous)
    delta = new_score - baseline
    if delta >= 6.0:
        return RiskTrend.INCREASING.value
    if delta <= -6.0:
        return RiskTrend.DECREASING.value
    return RiskTrend.STABLE.value


def score(
    bundle: FeatureBundle,
    rule_hits: Sequence[RuleHit],
    model: Optional[ProactiveRiskModel] = None,
    trend: str = RiskTrend.STABLE.value,
    explain: bool = True,
    probability: Optional[float] = None,
) -> RiskResult:
    """Blend the model and the rules engine into an explainable composite score.

    `explain=False` skips per-feature occlusion attribution. Attribution costs one
    extra model call per feature (19 calls instead of 1), which is the right price
    for an interactive request but far too expensive when bulk-scoring tens of
    thousands of rows. With it off, factors are derived from the fired rules alone
    and the composite score is unchanged.

    `probability` lets a caller supply a pre-computed model output - use it with
    `ProactiveRiskModel.predict_proba_batch()` to score a large batch in one
    matrix call instead of one call per row.
    """
    active_model = model or get_proactive_model()
    features = bundle.as_dict()

    if explain:
        prediction = active_model.predict(features)
    else:
        if probability is None:
            probability = active_model.predict_proba(features)
        prediction = Prediction(
            probability=probability,
            attributions=[],
            model_name=active_model.name,
            model_version=active_model.version,
            model_type=active_model.model_type,
            trained=active_model.trained,
            training_data=active_model.training_data,
            notes=active_model.notes,
            trained_at=active_model.trained_at,
        )

    model_points = prediction.probability * 100.0
    points_from_rules = rule_points(rule_hits)
    raw = MODEL_WEIGHT * model_points + RULES_WEIGHT * points_from_rules
    final_score = round(max(0.0, min(raw, 100.0)), 1)

    level = settings.risk_level_for(final_score)
    decision = settings.decision_for(level)

    return RiskResult(
        score=final_score,
        level=level,
        decision=decision,
        trend=trend,
        factors=build_factors(
            rule_hits, prediction.attributions, model_points, final_score
        ),
        features=features,
        model_probability=round(prediction.probability, 4),
        rule_hits=list(rule_hits),
        provenance=_provenance_from(prediction),
    )


def persist_assessment(
    db: Session,
    result: RiskResult,
    kind: str = AssessmentKind.PROACTIVE.value,
    customer: Optional[Customer] = None,
    transaction_id: Optional[int] = None,
    network_id: Optional[int] = None,
    assessed_at: Optional[datetime] = None,
    notes: str = "",
) -> RiskAssessment:
    """Write an immutable assessment row and refresh the customer snapshot."""
    provenance = result.provenance
    assessment = RiskAssessment(
        assessment_ref=f"RA-{uuid.uuid4().hex[:12].upper()}",
        kind=kind,
        customer_id=customer.id if customer else None,
        transaction_id=transaction_id,
        network_id=network_id,
        assessed_at=assessed_at or datetime.utcnow(),
        risk_score=result.score,
        risk_level=result.level,
        trend=result.trend,
        decision=result.decision,
        model_name=provenance.model_name if provenance else "unknown",
        model_version=provenance.model_version if provenance else "0.0.0",
        model_probability=result.model_probability,
        features=result.features,
        factors=result.factor_dicts(),
        notes=notes,
    )
    db.add(assessment)

    if customer is not None and kind == AssessmentKind.PROACTIVE.value:
        customer.current_risk_score = result.score
        customer.current_risk_level = result.level
        customer.risk_trend = result.trend
        if result.level in {"HIGH", "CRITICAL"}:
            customer.under_monitoring = True

    return assessment


def risk_band_counts(scores: Sequence[float]) -> Dict[str, int]:
    counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for value in scores:
        counts[settings.risk_level_for(value)] += 1
    return counts


def level_for(value: float) -> str:
    return settings.risk_level_for(value)
