from .base import BaseAgent


class FeedbackTriageAgent(BaseAgent):
    name = "feedback-triage"

    def run(self, status="Screened - Escalation", limit=50, auto_apply=False):
        feedback_items = self.get_resource(
            "feedback", params={"status": status, "limit": limit}
        )
        decisions = []
        for item in feedback_items:
            decision = "keep_escalated"
            if not item.get("is_inappropriate") and item.get("toxicity_score", 0.0) < 0.7:
                decision = "approve"
            decisions.append(
                {
                    "feedback_id": item.get("id"),
                    "status": item.get("status"),
                    "decision": decision,
                    "toxicity_score": item.get("toxicity_score"),
                }
            )

            if auto_apply and decision == "approve":
                self.call_tool("approve_feedback", {"feedback_id": item.get("id")})

        return decisions
