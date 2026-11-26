"""Orders. Amounts are integer cents (see .claude/DECISIONS.md, money-in-cents)."""


def order_total(items):
    return sum(i["price"] for i in items)
