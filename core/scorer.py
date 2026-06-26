"""
Scorer — accumulates points from all agents, determines final verdict.
Verdict bands per specification:
  0  – 40  → APPROVE
  41 – 65  → REVIEW
  66 – 85  → INVESTIGATE
  86 – 100 → REJECT
Override rules push the MINIMUM score up but never bypass the band system.
"""


class FraudScorer:

    def __init__(self):
        self.points = 0
        self.flags = []
        self.agent_scores = {}
        # Overrides push minimum score, never bypass bands
        self._min_score_floor = 0
        self._override_reasons = []

    def add(self, agent_name: str, pts: int, flags: list[str] | None = None):
        self.agent_scores[agent_name] = {"points": pts, "flags": flags or []}
        self.points += pts
        if flags:
            for f in flags:
                self.flags.append({"agent": agent_name, "flag": f})

    def set_override_reject(self, reason: str):
        """Rule 1 (>140% benchmark): push floor to 86 so band logic gives REJECT."""
        self._min_score_floor = max(self._min_score_floor, 86)
        self._override_reasons.append(reason)
        self.flags.append({"agent": "OVERRIDE", "flag": f"[Auto-Reject floor set] {reason}"})

    def set_override_review(self, reason: str):
        """Rule 3 (2+ claims / 90 days): push floor to 41 so band logic gives minimum REVIEW."""
        self._min_score_floor = max(self._min_score_floor, 41)
        self._override_reasons.append(reason)
        self.flags.append({"agent": "OVERRIDE", "flag": f"[Auto-Review floor set] {reason}"})

    @property
    def total(self) -> int:
        raw = min(self.points, 100)
        return max(raw, self._min_score_floor)

    @property
    def verdict(self) -> dict:
        score = self.total
        if score >= 86:
            return {
                "verdict": "REJECT",
                "level": "Fraud Confirmed",
                "band_color": "#1C1C1C",
                "text_color": "#FFFFFF",
                "action": "Reject claim. Log incident. Alert Special Investigation Unit."
            }
        if score >= 66:
            return {
                "verdict": "INVESTIGATE",
                "level": "High Risk",
                "band_color": "#8B1A1A",
                "text_color": "#FFFFFF",
                "action": "Refer to investigation unit. Do not process without SIU clearance."
            }
        if score >= 41:
            return {
                "verdict": "REVIEW",
                "level": "Medium Risk",
                "band_color": "#B05E00",
                "text_color": "#FFFFFF",
                "action": "Senior officer manual review required before processing."
            }
        # 0 – 40
        return {
            "verdict": "APPROVE",
            "level": "Low Risk",
            "band_color": "#1A4D2E",
            "text_color": "#FFFFFF",
            "action": "Low suspicion. Proceed with settlement processing."
        }

    def summary(self) -> dict:
        v = self.verdict
        return {
            "total_score": self.total,
            "raw_score": self.points,
            "verdict": v["verdict"],
            "level": v["level"],
            "band_color": v["band_color"],
            "text_color": v["text_color"],
            "action": v["action"],
            "agent_scores": self.agent_scores,
            "flags": self.flags,
            "override_reasons": self._override_reasons,
        }
