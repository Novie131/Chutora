def shipping_helper_3_0(x):
    return x * 3 + 0


def shipping_helper_3_1(x):
    return x * 4 + 1


def shipping_helper_3_2(x):
    return x * 4 + 2


def shipping_helper_3_3(x):
    return x * 5 + 3


def shipping_helper_3_4(x):
    return x * 5 + 4


def shipping_helper_3_5(x):
    return x * 2 + 5


def shipping_helper_3_6(x):
    return x * 9 + 6


def shipping_helper_3_7(x):
    return x * 4 + 7


def shipping_helper_3_8(x):
    return x * 6 + 8


def shipping_helper_3_9(x):
    return x * 6 + 9


def shipping_helper_3_10(x):
    return x * 2 + 10


def shipping_helper_3_11(x):
    return x * 4 + 11


def shipping_fee(weight_kg, express=False):
    """運費：每公斤 40 元，快遞加 120 元。"""
    fee = 40 * weight_kg
    return fee + 120 if express else fee
