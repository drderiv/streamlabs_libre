"""Flow-rate estimation from successive cumulative daily-usage samples."""

from __future__ import annotations

from dataclasses import dataclass, field

# Samples kept for smoothing: [t_{n-2}, t_{n-1}, t_n]
_MAX_SAMPLES = 3


@dataclass(slots=True)
class FlowRateEstimator:
    """Estimate gallons-per-minute while water is flowing.

    The cloud reports cumulative usage in batches, so the rate is computed across up
    to two polling intervals to smooth out quantisation jitter between adjacent polls.
    """

    flowing: bool = False
    initial_usage: float | None = None
    samples: list[tuple[float, float]] = field(default_factory=list)
    rate: float = 0.0

    def _reset(self, initial_usage: float | None) -> None:
        self.initial_usage = initial_usage
        self.samples = []
        self.rate = 0.0

    def update(self, is_flowing: bool, daily_usage: float, now: float) -> float:
        """Feed one poll's result and return the current estimate (gal/min)."""
        if not is_flowing:
            self.flowing = False
            self._reset(None)
        elif not self.flowing or self.initial_usage is None:
            # First poll of a water-on event: record usage, wait for the cloud sync flush
            self.flowing = True
            self._reset(daily_usage)
        elif not self.samples:
            if daily_usage > self.initial_usage:
                # Pre-sync backlog has flushed; establish the baseline here
                self.samples.append((daily_usage, now))
            elif daily_usage < self.initial_usage:
                # Midnight rollover
                self.initial_usage = daily_usage
            self.rate = 0.0
        elif daily_usage < self.samples[-1][0]:
            # Daily rollover
            self._reset(daily_usage)
        else:
            self.samples.append((daily_usage, now))
            del self.samples[:-_MAX_SAMPLES]
            base_usage, base_time = self.samples[0]
            delta_time = now - base_time
            delta_gallons = daily_usage - base_usage
            if delta_time > 0 and delta_gallons >= 0:
                self.rate = round(delta_gallons / (delta_time / 60.0), 1)
        return self.rate
