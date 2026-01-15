import time
import threading
from collections import deque


class RateLimiter:
    """Token bucket rate limiter for web scraping"""

    def __init__(self, requests_per_minute: int = 10):
        self.requests_per_minute = requests_per_minute
        self.min_interval = 60.0 / requests_per_minute
        self.request_times = deque(maxlen=requests_per_minute)
        self.lock = threading.Lock()

    def wait(self):
        """Wait if necessary to respect rate limit"""
        with self.lock:
            now = time.time()

            # Clean old entries
            while self.request_times and now - self.request_times[0] > 60:
                self.request_times.popleft()

            # Check if we need to wait
            if len(self.request_times) >= self.requests_per_minute:
                sleep_time = 60 - (now - self.request_times[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)

            # Minimum interval between requests
            if self.request_times:
                time_since_last = now - self.request_times[-1]
                if time_since_last < self.min_interval:
                    time.sleep(self.min_interval - time_since_last)

            self.request_times.append(time.time())
