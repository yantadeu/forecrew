"""Monthly report of card transactions."""
from datetime import datetime


def monthly_totals(transactions, year, month):
    """Sum of amounts per merchant for one month. Transactions are dicts with 'at' (ISO 8601, UTC), 'merchant', 'amount'."""
    totals = {}
    for t in transactions:
        at = datetime.fromisoformat(t["at"])
        if at.year == year and at.month == month:
            totals[t["merchant"]] = totals.get(t["merchant"], 0) + t["amount"]
    return totals
