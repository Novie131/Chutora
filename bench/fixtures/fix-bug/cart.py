"""購物車：總價要套用折扣碼，折扣以百分比計，且不能讓總價低於 0。"""

DISCOUNTS = {"SAVE10": 10, "HALF": 50}


def total(items, code=None):
    subtotal = sum(price * qty for price, qty in items)
    pct = DISCOUNTS.get(code, 0)
    return subtotal - pct  # bug：把百分比當成金額扣
