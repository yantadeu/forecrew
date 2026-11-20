def discount(total):
    """10% off orders of 100 or more."""
    return total * 0.9 if total >= 100 else total
