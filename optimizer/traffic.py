"""Causal, bounded Holt forecast for background bandwidth utilization.

TrafficForecaster maintains per-node level and trend state and produces
multi-step ahead predictions with simple confidence intervals.
The original forecast_utilization() function is kept for backward compatibility.
"""
import math
from .models import finite


def capacity_advice(current, predicted, samples, mae=None, persistence_mae=None, enabled=True):
    """Operational headroom advice. A rising trend alone is not congestion."""
    threshold=.85
    if current >= threshold:
        return dict(state='observed_high',level='caution',threshold=threshold)
    if not enabled:
        return dict(state='disabled',level='info',threshold=threshold)
    if samples < 6:
        return dict(state='learning',level='info',threshold=threshold)
    if mae is None or persistence_mae is None or mae > persistence_mae+1e-12:
        return dict(state='unreliable',level='info',threshold=threshold)
    if predicted >= threshold:
        return dict(state='forecast_high',level='caution',threshold=threshold)
    return dict(state='normal',level='info',threshold=threshold)


# ---------------------------------------------------------------------------
# Backward-compatible single-step forecaster (original API)
# ---------------------------------------------------------------------------

def forecast_utilization(history, alpha=.6, beta=.2):
    finite(alpha, 'alpha', 0, 1)
    finite(beta, 'beta', 0, 1)
    if not history:
        raise ValueError('Traffic history cannot be empty')
    values = [finite(v, 'utilization', 0, 1) for v in history]
    level = values[0]
    trend = values[1] - values[0] if len(values) > 1 else 0.
    for value in values[1:]:
        previous = level
        level = alpha * value + (1 - alpha) * (level + trend)
        trend = beta * (level - previous) + (1 - beta) * trend
    return max(0., min(1., level + trend))


# ---------------------------------------------------------------------------
# Stateful per-node Holt Double Exponential Smoothing forecaster
# ---------------------------------------------------------------------------

class TrafficForecaster:
    """Stateful Holt Double Exponential Smoothing for one network node.

    Maintains running estimates of *level* (L) and *trend* (T) so that
    incremental observations can be pushed without replaying the entire
    history.  Produces bounded multi-step forecasts and simple confidence
    intervals derived from the root-mean-square residual of past observations.

    Parameters
    ----------
    alpha : float
        Level smoothing factor in (0, 1).  Higher values react faster.
    beta : float
        Trend smoothing factor in (0, 1).  Higher values track trend faster.
    max_history : int
        Maximum number of historical observations to retain for display /
        residual computation.
    """

    def __init__(self, alpha=0.6, beta=0.2, max_history=12):
        finite(alpha, 'alpha', 0, 1)
        finite(beta, 'beta', 0, 1)
        if type(max_history) is not int or not 2 <= max_history <= 120:
            raise ValueError('max_history must be an integer >= 2')
        self.alpha = alpha
        self.beta = beta
        self.max_history = max_history

        # Running state
        self._level: float | None = None
        self._trend: float = 0.0
        self._history: list[float] = []       # observed utilisation fractions
        self._residuals: list[float] = []     # |observed - one-step-ahead forecast|

    # ------------------------------------------------------------------
    # Initialise from a list of past observations (replaces old history).
    # ------------------------------------------------------------------

    def seed(self, history: list[float]) -> None:
        """Warm-start state from a list of historical utilisation values [0..1]."""
        values = [finite(v,'utilization',0,1) for v in history]
        if not values:
            self._level=None; self._trend=0.; self._history=[]; self._residuals=[]
            return
        self._level = values[0]
        self._trend = values[1] - values[0] if len(values) > 1 else 0.0
        self._residuals = []
        for value in values[1:]:
            one_step = max(0., min(1., self._level + self._trend))
            self._residuals.append(abs(value - one_step))
            prev_level = self._level
            self._level = self.alpha * value + (1 - self.alpha) * (self._level + self._trend)
            self._trend = self.beta * (self._level - prev_level) + (1 - self.beta) * self._trend
        self._history = list(values[-self.max_history:])
        self._residuals = self._residuals[-self.max_history:]

    # ------------------------------------------------------------------
    # Push a new observation and update state.
    # ------------------------------------------------------------------

    def update(self, observed: float) -> None:
        """Push a new utilisation observation and update the running state."""
        observed = finite(observed,'utilization',0,1)
        if self._level is None:
            self._level = observed
            self._history.append(observed)
            return
        one_step = max(0., min(1., self._level + self._trend))
        self._residuals.append(abs(observed - one_step))
        if len(self._residuals) > self.max_history:
            self._residuals.pop(0)
        prev_level = self._level
        self._level = self.alpha * observed + (1 - self.alpha) * (self._level + self._trend)
        self._trend = self.beta * (self._level - prev_level) + (1 - self.beta) * self._trend
        self._history.append(observed)
        if len(self._history) > self.max_history:
            self._history.pop(0)

    # ------------------------------------------------------------------
    # Multi-step forecast
    # ------------------------------------------------------------------

    def forecast(self, steps: int = 6) -> dict:
        """Return a *steps*-ahead forecast with confidence intervals.

        Returns
        -------
        dict with keys:
            history   : list of historical utilisation values (last max_history)
            forecast  : list of *steps* predicted utilisation values
            confidence_lo : lower bound (forecast - 1.96 * sigma * sqrt(h))
            confidence_hi : upper bound
            trend     : 'increasing' | 'stable' | 'decreasing'
            level     : current smoothed level
            slope     : current smoothed trend per step
        """
        if type(steps) is not int or not 1 <= steps <= 24:
            raise ValueError('steps must be an integer in [1,24]')
        if self._level is None:
            # No data yet — return flat zeros
            zeros = [0.0] * steps
            return dict(history=list(self._history), forecast=zeros,
                        confidence_lo=zeros, confidence_hi=zeros,
                        trend='stable', level=0.0, slope=0.0)

        # Root-mean-square of past one-step residuals as base sigma
        if self._residuals:
            sigma = math.sqrt(sum(r * r for r in self._residuals) / len(self._residuals))
        else:
            sigma = 0.05  # default when no residual data

        preds, lo, hi = [], [], []
        for h in range(1, steps + 1):
            raw = self._level + h * self._trend
            clipped = max(0., min(1., raw))
            preds.append(round(clipped, 4))
            # Confidence interval widens with horizon: sigma * sqrt(h)
            margin = min(0.5, 1.96 * sigma * math.sqrt(h))
            lo.append(round(max(0., clipped - margin), 4))
            hi.append(round(min(1., clipped + margin), 4))

        # Trend direction: compare h=1 vs h=steps forecast
        delta = preds[-1] - preds[0] if steps > 1 else self._trend
        if delta > 0.03:
            trend = 'increasing'
        elif delta < -0.03:
            trend = 'decreasing'
        else:
            trend = 'stable'

        return dict(
            history=[round(v, 4) for v in self._history],
            forecast=preds,
            confidence_lo=lo,
            confidence_hi=hi,
            trend=trend,
            level=round(self._level, 4),
            slope=round(self._trend, 6),
        )

    # ------------------------------------------------------------------
    # Convenience: single-step predicted utilisation fraction
    # ------------------------------------------------------------------

    @property
    def last_observation(self):
        return self._history[-1] if self._history else 0.

    @property
    def next_utilisation(self) -> float:
        """Best single-step-ahead utilisation estimate, clamped to [0, 1]."""
        if self._level is None:
            return 0.0
        return max(0., min(1., self._level + self._trend))

    @property
    def trend_slope(self) -> float:
        """Normalised trend slope; positive = load growing, negative = shrinking."""
        return self._trend
