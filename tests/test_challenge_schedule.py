import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import bot


class ChallengeScheduleTest(unittest.TestCase):
    def test_next_challenge_can_use_current_slot_when_not_sent_yet(self):
        now = datetime(2026, 6, 8, 8, 0, tzinfo=timezone.utc)

        with (
            patch.object(bot, 'CHALLENGES_PER_DAY', 3),
            patch('bot.random.randint', return_value=7200),
        ):
            next_challenge = bot.get_next_challenge_at(now)

        self.assertEqual(
            next_challenge,
            datetime(2026, 6, 8, 9, 0, tzinfo=timezone.utc),
        )

    def test_next_challenge_after_sent_uses_next_daily_slot(self):
        now = datetime(2026, 6, 8, 8, 0, tzinfo=timezone.utc)

        with (
            patch.object(bot, 'CHALLENGES_PER_DAY', 3),
            patch('bot.random.randint', return_value=0),
        ):
            next_challenge = bot.get_next_challenge_at(now, skip_current_slot=True)

        self.assertEqual(
            next_challenge,
            datetime(2026, 6, 8, 10, 40, tzinfo=timezone.utc),
        )

    def test_next_challenge_moves_to_tomorrow_after_daily_window(self):
        now = datetime(2026, 6, 8, 19, 0, tzinfo=timezone.utc)

        with (
            patch.object(bot, 'CHALLENGES_PER_DAY', 3),
            patch('bot.random.randint', return_value=0),
        ):
            next_challenge = bot.get_next_challenge_at(now)

        self.assertEqual(
            next_challenge,
            datetime(2026, 6, 9, 7, 0, tzinfo=timezone.utc),
        )


if __name__ == '__main__':
    unittest.main()
