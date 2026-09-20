"""Small input gate for visual transitions; engine/session commit before animation."""
from __future__ import annotations

from .solution_archive import normalize_actions

SPEEDS = {"Instant": 0, "Fast": 160, "Normal": 320, "Slow": 650}


class PlayController:
    def __init__(self, session, animate, refresh):
        self.session = session
        self.animate = animate
        self.refresh = refresh
        self.speed = "Normal"
        self.busy = False

    def run(self, operation, *, animated=True) -> bool:
        """Ignore repeated input while busy; never queue stale card coordinates."""
        if self.busy:
            return False
        before_id, before = self.session.current, self.session.state
        self.busy = True
        try:
            operation()  # authoritative state + durable save happen synchronously
            after = self.session.state
            node = self.session.node
            action = (normalize_actions([node.action])[0]
                      if node.parent == before_id else None)
            duration = SPEEDS[self.speed] if animated and action else 0
            self.refresh(draw_board=False)  # clean record changes immediately
            if duration:
                self.animate(before, after, action, duration, self.finish)
            else:
                self.finish()
        except Exception:
            self.busy = False
            self.refresh()
            raise
        return True

    def finish(self):
        self.busy = False
        self.refresh()
