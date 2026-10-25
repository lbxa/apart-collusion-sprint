"""Exact token amounts and arithmetic, independent of Decimal's global context."""

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

Amount = Decimal | int | float


def integer_units(value: Amount, scale: int, label: str) -> int:
    """Validate and scale an input using integers, never Decimal context math."""
    try:
        amount = _decimal(value)
        if amount < 0 or scale <= 0:
            raise ValueError
        parts = amount.as_tuple()
        coefficient = int("".join(map(str, parts.digits))) * scale
        if parts.exponent >= 0:
            return coefficient * 10 ** parts.exponent
        units, remainder = divmod(coefficient, 10 ** -parts.exponent)
        if remainder:
            raise ValueError
        return units
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{label} must be nonnegative and exactly representable at scale {scale}") from None


def base_units_to_tokens(value: str | int, decimals: int = 2) -> Decimal:
    """Scale an integer by a power of ten without rounding even uint256 values."""
    if decimals < 0:
        raise ValueError("Decimal places must be nonnegative")
    units = Decimal(value)
    if not units.is_finite() or units != units.to_integral_value():
        raise ValueError("Base units must be a finite integer")
    parts = units.as_tuple()
    return Decimal((parts.sign, parts.digits, parts.exponent - decimals))


def _decimal(value: Amount | str) -> Decimal:
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite():
        raise ValueError("Financial amounts must be finite")
    return amount


def financial_sum(values: Iterable[Amount]) -> Amount:
    """Sum exactly when any operand is Decimal; retain legacy mock float behavior."""
    amounts = list(values)
    if not any(isinstance(value, Decimal) for value in amounts):
        return sum(amounts)
    parts = [_decimal(value).as_tuple() for value in amounts]
    exponent = min(part.exponent for part in parts)
    total = sum(
        (-1 if part.sign else 1) * int("".join(map(str, part.digits)))
        * 10 ** (part.exponent - exponent)
        for part in parts
    )
    return Decimal((int(total < 0), tuple(map(int, str(abs(total)))), exponent))


def financial_difference(left: Amount, right: Amount) -> Amount:
    # copy_negate does not round under a caller's Decimal context.
    negative = right.copy_negate() if isinstance(right, Decimal) else -right
    return financial_sum([left, negative])


def financial_product(left: Amount, right: Amount) -> Amount:
    """Multiply exact and legacy values without mixing Decimal and float."""
    if not isinstance(left, Decimal) and not isinstance(right, Decimal):
        return left * right
    left_parts, right_parts = _decimal(left).as_tuple(), _decimal(right).as_tuple()
    coefficient = int("".join(map(str, left_parts.digits))) * int("".join(map(str, right_parts.digits)))
    return Decimal((left_parts.sign ^ right_parts.sign, tuple(map(int, str(coefficient))),
                    left_parts.exponent + right_parts.exponent))


def display_share(amount: Amount, count: int) -> Amount:
    """Split an estimated prompt/mock payout; contract settlement remains authoritative."""
    if not isinstance(amount, Decimal):
        return amount / count
    with localcontext() as context:
        context.prec = max(28, len(amount.as_tuple().digits) + len(str(count)) + 28)
        return amount / count


def restore_amount(value: Amount | str) -> Amount:
    """Restore exact JSON strings while accepting historical numeric records."""
    return _decimal(value) if isinstance(value, str) else value


def financial_json(value: Any) -> Any:
    """Encode exact decimal amounts as strings rather than binary JSON numbers."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: financial_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [financial_json(item) for item in value]
    return value
