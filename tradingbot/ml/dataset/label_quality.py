"""Label quality and bias detection for ML datasets."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from tradingbot.ml.dataset.schema import Label


@dataclass
class LabelQualityReport:
    status: str
    class_imbalance_warnings: list[str] = field(default_factory=list)
    possible_event_bias: bool = False
    dominant_event_type: str | None = None
    event_win_share: float = 0.0
    possible_session_bias: bool = False
    dominant_session: str | None = None
    direction_bias: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _session_from_row(row: pd.Series) -> str:
    if row.get("session_london", 0) == 1:
        return "london"
    if row.get("session_ny", 0) == 1:
        return "new_york"
    if row.get("session_asia", 0) == 1:
        return "asia"
    if row.get("session_off", 0) == 1:
        return "off_hours"
    return "unknown"


class LabelQualityValidator:
    """Detect class imbalance, event/session/direction bias in labeled datasets."""

    def __init__(
        self,
        *,
        min_class_ratio: float = 0.20,
        event_bias_threshold: float = 0.90,
        session_bias_threshold: float = 0.70,
        direction_imbalance_threshold: float = 0.15,
    ) -> None:
        self.min_class_ratio = min_class_ratio
        self.event_bias_threshold = event_bias_threshold
        self.session_bias_threshold = session_bias_threshold
        self.direction_imbalance_threshold = direction_imbalance_threshold

    def validate(self, df: pd.DataFrame) -> LabelQualityReport:
        report = LabelQualityReport(status="pass")
        if df is None or df.empty or "label" not in df.columns:
            report.status = "fail"
            report.issues.append("empty dataset or missing label column")
            return report

        n = len(df)
        tp = int((df["label"] == int(Label.TP_FIRST)).sum())
        sl = int((df["label"] == int(Label.SL_FIRST)).sum())
        resolved = tp + sl

        if resolved > 0:
            tp_ratio = tp / resolved
            sl_ratio = sl / resolved
            if tp_ratio < self.min_class_ratio:
                report.class_imbalance_warnings.append(
                    f"label 1 (TP first) below {self.min_class_ratio:.0%}: {tp_ratio:.2%}"
                )
            if sl_ratio < self.min_class_ratio:
                report.class_imbalance_warnings.append(
                    f"label 0 (SL first) below {self.min_class_ratio:.0%}: {sl_ratio:.2%}"
                )

        # Event bias — concentration of winners from one event type
        if resolved > 0 and "event_type" in df.columns:
            winners = df[df["label"] == int(Label.TP_FIRST)]
            if not winners.empty:
                top_event = winners["event_type"].value_counts().idxmax()
                top_share = float(winners["event_type"].value_counts().max() / len(winners))
                report.dominant_event_type = str(top_event)
                report.event_win_share = round(top_share, 4)
                if top_share >= self.event_bias_threshold:
                    report.possible_event_bias = True
                    report.issues.append(
                        f"{top_share:.0%} of winners from event type '{top_event}'"
                    )

        # Session bias — dominant session in dataset
        if not df.empty:
            sessions = df.apply(_session_from_row, axis=1)
            if not sessions.empty:
                dominant = sessions.value_counts().idxmax()
                share = float(sessions.value_counts().max() / n)
                report.dominant_session = str(dominant)
                if share >= self.session_bias_threshold:
                    report.possible_session_bias = True
                    report.issues.append(
                        f"{share:.0%} of samples in session '{dominant}'"
                    )

        # Direction bias
        if "direction" in df.columns and resolved > 0:
            buy = df[df["direction"] > 0]
            sell = df[df["direction"] < 0]
            buy_wr = self._winrate(buy)
            sell_wr = self._winrate(sell)
            buy_resolved = buy[buy["label"].isin([0, 1])] if not buy.empty else buy
            sell_resolved = sell[sell["label"].isin([0, 1])] if not sell.empty else sell
            report.direction_bias = {
                "buy_winrate": buy_wr,
                "sell_winrate": sell_wr,
                "buy_count": int(len(buy)),
                "sell_count": int(len(sell)),
            }
            if (
                not buy_resolved.empty
                and not sell_resolved.empty
                and abs(buy_wr - sell_wr) >= self.direction_imbalance_threshold
            ):
                report.direction_bias["warning"] = "direction imbalance"
                report.issues.append(
                    f"buy winrate {buy_wr:.2%} vs sell winrate {sell_wr:.2%}"
                )

        if report.class_imbalance_warnings or report.possible_event_bias or report.possible_session_bias:
            report.status = "warn"
        if report.status == "fail":
            pass
        elif any("fail" in w for w in report.issues):
            report.status = "fail"

        return report

    @staticmethod
    def _winrate(subset: pd.DataFrame) -> float:
        if subset.empty:
            return 0.0
        resolved = subset[subset["label"].isin([0, 1])]
        if resolved.empty:
            return 0.0
        return round(float((resolved["label"] == int(Label.TP_FIRST)).sum() / len(resolved)), 4)
