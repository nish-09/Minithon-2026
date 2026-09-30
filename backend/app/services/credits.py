"""Non-monetary Help Credits: reciprocity, not a marketplace.

Policy: receiving help never gets blocked by a low balance (critical help must always flow); the
debit is clamped so a balance never goes negative. Donations are the only place a shortfall is an error.
"""
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import CreditTransaction, HelpCredit, User


class CreditError(Exception):
    pass


def ensure_account(db: Session, user_id: int) -> HelpCredit:
    acc = db.get(HelpCredit, user_id)
    if acc is None:
        acc = HelpCredit(user_id=user_id, balance=get_settings().starting_credits)
        db.add(acc)
        db.add(CreditTransaction(user_id=user_id, amount=acc.balance, kind="grant"))
        db.flush()
    return acc


def balance(db: Session, user_id: int) -> int:
    return ensure_account(db, user_id).balance


def earn(db: Session, user_id: int, amount: int, request_id: int | None = None, counterparty_id: int | None = None) -> int:
    ensure_account(db, user_id)
    db.execute(update(HelpCredit).where(HelpCredit.user_id == user_id).values(balance=HelpCredit.balance + amount))
    db.add(CreditTransaction(user_id=user_id, amount=amount, kind="earned", request_id=request_id, counterparty_id=counterparty_id))
    return amount


def spend_clamped(db: Session, user_id: int, amount: int, request_id: int | None = None, counterparty_id: int | None = None) -> int:
    acc = ensure_account(db, user_id)
    actual = min(amount, acc.balance)
    if actual > 0:
        db.execute(update(HelpCredit).where(HelpCredit.user_id == user_id).values(balance=HelpCredit.balance - actual))
        db.add(CreditTransaction(user_id=user_id, amount=-actual, kind="spent", request_id=request_id, counterparty_id=counterparty_id))
    return actual


def donate(db: Session, from_id: int, to_id: int, amount: int) -> None:
    if amount <= 0:
        raise CreditError("Amount must be positive")
    if from_id == to_id:
        raise CreditError("You cannot donate to yourself")
    if db.get(User, to_id) is None:
        raise CreditError("Recipient not found")
    ensure_account(db, from_id)
    ensure_account(db, to_id)
    # conditional update => no overdraft even under concurrent donations
    res = db.execute(update(HelpCredit).where(HelpCredit.user_id == from_id, HelpCredit.balance >= amount)
                     .values(balance=HelpCredit.balance - amount))
    if res.rowcount != 1:
        raise CreditError("Insufficient credits")
    db.execute(update(HelpCredit).where(HelpCredit.user_id == to_id).values(balance=HelpCredit.balance + amount))
    db.add(CreditTransaction(user_id=from_id, amount=-amount, kind="donated", counterparty_id=to_id))
    db.add(CreditTransaction(user_id=to_id, amount=amount, kind="received", counterparty_id=from_id))


def history(db: Session, user_id: int, limit: int = 50) -> list[CreditTransaction]:
    return list(db.scalars(select(CreditTransaction).where(CreditTransaction.user_id == user_id)
                           .order_by(CreditTransaction.id.desc()).limit(limit)))
