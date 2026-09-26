"""D-134 history download concurrent with the first snapshot; no network."""
import asyncio
import unittest
from unittest.mock import patch

from kalshi_bot.values import InvalidData
from tests import test_bot_account_release as baseline
from tests import test_bot_routine_refresh as routine


class HistoryPrefetchTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = baseline.AccountReleaseTests.asyncSetUp
    asyncTearDown = baseline.AccountReleaseTests.asyncTearDown
    open_epoch = baseline.AccountReleaseTests.open_epoch
    refresh = baseline.AccountReleaseTests.refresh
    reserve = baseline.AccountReleaseTests.reserve
    runtime = routine.RoutineRefreshTests.runtime
    advance = routine.RoutineRefreshTests.advance

    def fresh_pass(self, runtime):
        runtime.request_recovery()
        runtime.recovery_requested.clear()
        self.advance(1)

    def claims(self, runtime):
        created = []
        original = runtime.account.prefetch_history
        def track(*args, **kwargs):
            created.append(original(*args, **kwargs))
            return created[-1]
        return created, patch.object(runtime.account, 'prefetch_history', track)

    async def test_history_download_overlaps_first_snapshot(self):
        runtime = await self.runtime()
        self.fresh_pass(runtime)
        history_started = asyncio.Event()
        original_read, original_collect = runtime.reads.read, runtime.reads.collect
        async def read(name, **kwargs):
            if name == 'cutoff':
                history_started.set()
            return await original_read(name, **kwargs)
        async def collect(name, **kwargs):
            if name == 'positions' and not runtime.account.report:
                # The first snapshot cannot finish until history has started.
                await asyncio.wait_for(history_started.wait(), 1)
            return await original_collect(name, **kwargs)
        runtime.reads.read, runtime.reads.collect = read, collect
        self.assertTrue(await asyncio.wait_for(runtime.recover_once(), 5))

    async def test_prefetch_records_its_real_read_start(self):
        runtime = await self.runtime()
        self.fresh_pass(runtime)
        created, tracking = self.claims(runtime)
        with tracking:
            self.assertTrue(await runtime.recover_once())
        started = created[0][1]
        history = runtime.last_reports[0]
        self.assertEqual(history.enumeration.read_started_us,
                         int(started.timestamp())*1_000_000+started.microsecond)

    async def test_private_event_after_download_start_fetches_again(self):
        runtime = await self.runtime()
        self.fresh_pass(runtime)
        account = runtime.account
        claim = account.prefetch_history(runtime.reads, start=runtime.history_start,
                                         end=self.now, now=lambda: self.now)
        account.revision += 1  # A private event after the download began.
        runtime.reads.calls.clear()
        history = await account.recover_history(runtime.reads, start=runtime.history_start,
            end=self.now, now=lambda: self.now, prefetched=claim)
        self.assertIsNotNone(history)
        self.assertTrue(claim[0].done())
        # The stale download is discarded; a fresh one reads the cutoff twice.
        self.assertEqual(runtime.reads.calls.count('cutoff'), 2)

    async def test_failed_or_stale_first_snapshot_never_orphans_download(self):
        runtime = await self.runtime()
        for outcome in ('raise', 'none'):
            with self.subTest(outcome=outcome):
                self.fresh_pass(runtime)
                created, tracking = self.claims(runtime)
                async def first(*args, **kwargs):
                    await asyncio.sleep(0)
                    if outcome == 'raise':
                        raise InvalidData('snapshot failed')
                    return None
                with tracking, patch.object(runtime.account, 'reconcile', first):
                    if outcome == 'raise':
                        with self.assertRaises(InvalidData):
                            await runtime.recover_once()
                    else:
                        self.assertFalse(await runtime.recover_once())
                self.assertEqual(len(created), 1)
                self.assertTrue(created[0][0].done())


if __name__ == '__main__':
    unittest.main()
