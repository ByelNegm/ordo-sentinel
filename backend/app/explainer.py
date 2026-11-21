"""Builder C: async explanation interface; skeleton uses safe fixture templates."""
from .models import Alert, Explanation


async def explain(alert: Alert) -> Explanation:
    """Return EN/AR and analyst text; future LLM/cache must always fall back."""
    return Explanation(customer_message=alert.customer_message.model_copy(deep=True),
                       analyst_explanation=alert.analyst_explanation)
