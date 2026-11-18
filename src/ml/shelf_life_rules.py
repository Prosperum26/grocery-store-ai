"""Shelf-life rules applied after the model has scored the candidates.

Instacart has no expiry data, so the model did not learn any of this.

lot_expiring  The lot on sale expires in fewer than `min_lot_days` days.
              Only checked when the caller sends a lot date: the catalog has none yet.
not_due       The last purchase is probably still usable and not used up:
              days since it < the category's shelf life, and
              days since it < not_due_ratio * the customer's own mean gap.
              A product bought only once has no gap, so it is never held back.
              Off by default: on Instacart val it lowers Recall (docs/report.md).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleConfig:
    shelf_life_days: dict[str, int]
    min_lot_days: int
    not_due_ratio: float
    not_due_enabled: bool = False


def suppression_reason(
    category: str | None,
    days_since: float,
    mean_gap: float | None,
    lot_days_left: float | None,
    cfg: RuleConfig,
) -> str | None:
    """The rule that removes this product, or None to keep it."""
    if lot_days_left is not None and lot_days_left < cfg.min_lot_days:
        return "lot_expiring"
    shelf = cfg.shelf_life_days.get(category or "")
    if (
        cfg.not_due_enabled
        and shelf is not None
        and mean_gap is not None
        and days_since < shelf
        and days_since < cfg.not_due_ratio * mean_gap
    ):
        return "not_due"
    return None
