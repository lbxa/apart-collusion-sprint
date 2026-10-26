"""Real local game lifecycle for harness policy and export regressions."""

import unittest

from game_api.core_engine import CoreEngineAPI


class CoreTestCase(unittest.IsolatedAsyncioTestCase):
    def new_game(self, factory=CoreEngineAPI):
        """Own each adapter through cleanup, including partial startup failures."""
        game = factory()
        self.addAsyncCleanup(game.stop)
        return game
