"""Shadow-only entry screen (architecture review #9, Finding 210).

Scores each prepared entry pair against two proposed fill-avoidance rules and
reports the result. It never blocks, delays or changes an order: the numbers
are logged so the rules can be judged against real fills before any decision.

- Volume rule: markets that traded more than about 2,000 contracts in the week
  before quoting were swept far more often; ``volume_24h`` × 7 approximates it.
- Reward-vs-risk rule: the program's remaining projected reward should be at
  least a fraction of the worst-case loss of one entry fill.
"""
from decimal import Decimal

WEEKLY_VOLUME_LIMIT = Decimal(2000)
REWARD_TO_RISK_MIN = Decimal('0.25')


def worst_fill_loss(quotes):
    """Largest loss if one leg fills and the market resolves against it."""
    losses = [q.quantity*(q.yes_price if q.side == 'bid' else 1-q.yes_price)
              for q in quotes]
    return max(losses) if losses else None


def screen(*, remaining_reward, quotes, volume_24h):
    """Classify one entry pair; ``None`` inputs are reported, never guessed."""
    risk = worst_fill_loss(quotes)
    heavy = volume_24h is not None and volume_24h*7 > WEEKLY_VOLUME_LIMIT
    thin = (remaining_reward is not None and risk is not None and risk > 0
            and remaining_reward < risk*REWARD_TO_RISK_MIN)
    verdict = ('both' if heavy and thin else 'volume' if heavy
               else 'reward_risk' if thin else 'pass')
    if volume_24h is None or remaining_reward is None or risk is None:
        verdict = 'unknown' if verdict == 'pass' else verdict
    return dict(verdict=verdict, risk=risk, reward=remaining_reward, volume_24h=volume_24h)


def cents(value):
    return None if value is None else int(value*100)
