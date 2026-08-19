"""The rules engine.

Loads enabled rules from the database, evaluates them against a feature/metric
dictionary, and returns the fired rules with their point contributions and
rendered explanations. Thresholds live in the database, so the engine's behaviour
follows what an admin configured on the Rules Engine page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml.features import FEATURE_BY_NAME, describe_value
from app.models import Rule
from app.rules.definitions import RULES_BY_CODE

_OPERATORS = {
    "GT": lambda value, threshold: value > threshold,
    "GTE": lambda value, threshold: value >= threshold,
    "LT": lambda value, threshold: value < threshold,
    "LTE": lambda value, threshold: value <= threshold,
    "EQ": lambda value, threshold: abs(value - threshold) < 1e-9,
}


@dataclass
class RuleHit:
    """One rule that fired, with everything needed to explain it."""

    code: str
    name: str
    category: str
    severity: str
    layer: str
    feature: str
    observed: float
    threshold: float
    operator: str
    threshold_unit: str
    contribution: float
    explanation: str

    def as_factor(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "label": self.name,
            "contribution": round(self.contribution, 1),
            "detail": self.explanation,
            "category": self.category,
        }


def _format_value(feature: str, value: float, unit: str) -> str:
    """Render an observed value the way the explanation template expects."""
    if feature in FEATURE_BY_NAME:
        return describe_value(feature, value)
    if unit == "INR":
        return f"{value:,.2f}"
    if unit == "ratio":
        return f"{value * 100:.0f}%"
    if unit == "x baseline":
        return f"{value:.1f}"
    if unit == "flag":
        return "yes" if value >= 0.5 else "no"
    if unit == "years":
        return f"{value:.1f} years"
    return f"{value:,.0f}" if abs(value) >= 100 else f"{value:.2f}"


def _format_threshold(threshold: float, unit: str) -> str:
    if unit == "INR":
        return f"{threshold:,.0f}"
    if unit == "ratio":
        return f"{threshold * 100:.0f}%"
    return f"{threshold:g}"


def load_rules(
    db: Session,
    layer: Optional[str] = None,
    enabled_only: bool = True,
    layers: Optional[Sequence[str]] = None,
) -> List[Rule]:
    stmt = select(Rule)
    if layers:
        stmt = stmt.where(Rule.layer.in_(list(layers)))
    elif layer:
        stmt = stmt.where(Rule.layer == layer)
    if enabled_only:
        stmt = stmt.where(Rule.enabled.is_(True))
    return list(db.scalars(stmt.order_by(Rule.score_weight.desc())).all())


# Behavioural rules are computed from a customer's OWN transaction history, so
# every one of them is knowable before the next transaction is authorised. The
# PROACTIVE/REACTIVE split in the catalogue describes which detector narrates a
# finding to the investigator - it is not a statement about score eligibility.
# Excluding the REACTIVE ones from proactive scoring would drop a mule account's
# single most diagnostic signal (rapid pass-through) from its own risk score.
BEHAVIOURAL_LAYERS = ("PROACTIVE", "REACTIVE")


def load_behavioural_rules(db: Session) -> List[Rule]:
    """Every rule that scores customer behaviour, regardless of narrating layer.

    NETWORK and INTEGRITY rules are deliberately excluded: those are scored by
    the graph engine and the integrity gateway respectively, on different inputs.
    """
    return load_rules(db, layers=BEHAVIOURAL_LAYERS)


def evaluate(
    rules: Sequence[Rule], metrics: Dict[str, float], increment_counts: bool = False
) -> List[RuleHit]:
    """Evaluate `rules` against `metrics`; return only the rules that fired.

    Rules whose feature is absent from `metrics` are skipped rather than treated
    as zero, so a layer never fires a rule it has no data for.
    """
    hits: List[RuleHit] = []

    for rule in rules:
        definition = RULES_BY_CODE.get(rule.code)
        feature = definition.feature if definition else rule.code.lower()
        if feature not in metrics:
            continue

        value = float(metrics[feature] or 0.0)
        comparator = _OPERATORS.get(rule.operator.upper())
        if comparator is None or not comparator(value, float(rule.threshold)):
            continue

        template = (
            definition.explanation
            if definition and definition.explanation
            else "{value} breached the configured threshold of {threshold}."
        )
        explanation = template.format(
            value=_format_value(feature, value, rule.threshold_unit),
            threshold=_format_threshold(float(rule.threshold), rule.threshold_unit),
        )

        hits.append(
            RuleHit(
                code=rule.code,
                name=rule.name,
                category=rule.category,
                severity=rule.severity,
                layer=rule.layer,
                feature=feature,
                observed=value,
                threshold=float(rule.threshold),
                operator=rule.operator,
                threshold_unit=rule.threshold_unit,
                contribution=float(rule.score_weight),
                explanation=explanation,
            )
        )

        if increment_counts:
            rule.triggered_count = (rule.triggered_count or 0) + 1

    hits.sort(key=lambda h: h.contribution, reverse=True)
    return hits


def rule_points(hits: Iterable[RuleHit]) -> float:
    """Total rule contribution, capped at the 0-100 score scale."""
    return min(sum(hit.contribution for hit in hits), 100.0)


def max_severity(hits: Iterable[RuleHit]) -> str:
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    best = "LOW"
    for hit in hits:
        if order.get(hit.severity, 0) > order.get(best, 0):
            best = hit.severity
    return best


def sync_rule_catalogue(db: Session) -> int:
    """Insert any rule definitions missing from the database.

    Existing rows are left untouched so operator retuning is never overwritten
    by a redeploy.
    """
    existing = {row.code for row in db.scalars(select(Rule)).all()}
    created = 0
    for definition in RULES_BY_CODE.values():
        if definition.code in existing:
            continue
        db.add(
            Rule(
                code=definition.code,
                name=definition.name,
                description=definition.description,
                category=definition.category,
                severity=definition.severity,
                layer=definition.layer,
                enabled=definition.enabled,
                threshold=definition.threshold,
                operator=definition.operator,
                threshold_unit=definition.threshold_unit,
                score_weight=definition.score_weight,
                params=dict(definition.params),
                triggered_count=0,
            )
        )
        created += 1
    return created
