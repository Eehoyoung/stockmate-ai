import os
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import redis_writer


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    def hmset(self, key, mapping):
        self.commands.append(("hmset", key, mapping))
        self.redis.hashes[key] = dict(mapping)
        return self

    def expire(self, key, ttl):
        self.commands.append(("expire", key, ttl))
        self.redis.expires.append((key, ttl))
        return self

    def lpush(self, key, value):
        self.commands.append(("lpush", key, value))
        self.redis.lists.setdefault(key, []).insert(0, value)
        return self

    def ltrim(self, key, start, end):
        self.commands.append(("ltrim", key, start, end))
        self.redis.ltrims.append((key, start, end))
        self.redis.lists[key] = self.redis.lists.get(key, [])[start:end + 1]
        return self

    async def execute(self):
        self.redis.pipeline_batches.append(list(self.commands))
        return [True] * len(self.commands)


class FakeRedis:
    def __init__(self):
        self.calls = []
        self.expires = []
        self.ltrims = []
        self.lranges = []
        self.hashes = {}
        self.lists = {}
        self.sets = []
        self.pipeline_batches = []

    def pipeline(self, transaction=False):
        self.calls.append(("pipeline", transaction))
        return FakePipeline(self)

    async def hmset(self, key, mapping):
        self.calls.append(("hmset", key, mapping))
        self.hashes[key] = dict(mapping)
        return True

    async def expire(self, key, ttl):
        self.calls.append(("expire", key, ttl))
        self.expires.append((key, ttl))
        return True

    async def lpush(self, key, value):
        self.calls.append(("lpush", key, value))
        self.lists.setdefault(key, []).insert(0, value)
        return True

    async def ltrim(self, key, start, end):
        self.calls.append(("ltrim", key, start, end))
        self.ltrims.append((key, start, end))
        self.lists[key] = self.lists.get(key, [])[start:end + 1]
        return True

    async def lrange(self, key, start, end):
        self.calls.append(("lrange", key, start, end))
        self.lranges.append((key, start, end))
        return self.lists.get(key, [])[start:end + 1]

    async def set(self, key, value, ex=None):
        self.calls.append(("set", key, value, ex))
        self.sets.append((key, value, ex))
        return True


class RedisWriterTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ, {
            "WS_REDIS_PIPELINE_ENABLED": "",
            "WS_REDIS_EXPIRE_THROTTLE_MS": "0",
            "WS_REDIS_LTRIM_THROTTLE_MS": "0",
            "WS_REDIS_DEDUPE_ENABLED": "",
            "WS_REDIS_DEDUPE_TTL_MS": "500",
            "WS_REDIS_STRENGTH_AVG_SAMPLE_EVERY": "1",
        }, clear=False)
        self.env_patch.start()
        redis_writer._last_expire_ms.clear()
        redis_writer._last_ltrim_ms.clear()
        redis_writer._last_write_sig.clear()
        redis_writer._strength_samples.clear()
        redis_writer._strength_sample_counts.clear()

    def tearDown(self):
        self.env_patch.stop()

    async def test_default_tick_keeps_existing_write_shape(self):
        rdb = FakeRedis()

        await redis_writer.write_tick(rdb, {
            "10": "1000",
            "11": "+10",
            "12": "1.0",
            "13": "100",
            "14": "100000",
            "20": "093000",
            "228": "123.4",
        }, "A005930")

        self.assertIn(("hmset", "ws:tick:005930", rdb.hashes["ws:tick:005930"]), rdb.calls)
        self.assertIn(("expire", "ws:tick:005930", 600), rdb.calls)
        self.assertIn(("ltrim", "ws:strength:005930", 0, 9), rdb.calls)
        self.assertIn(("lrange", "ws:strength:005930", 0, 4), rdb.calls)
        self.assertEqual(rdb.hashes["ws:strength_meta:005930"]["avg_5"], "123.4")

    async def test_pipeline_and_expire_throttle_are_opt_in(self):
        os.environ["WS_REDIS_PIPELINE_ENABLED"] = "1"
        os.environ["WS_REDIS_EXPIRE_THROTTLE_MS"] = "1000"
        rdb = FakeRedis()

        with patch("redis_writer._now_ms", side_effect=[1000, 1100]):
            await redis_writer.write_hoga(rdb, {"125": "1"}, "005930")
            await redis_writer.write_hoga(rdb, {"125": "2"}, "005930")

        self.assertEqual(
            [command[0] for command in rdb.pipeline_batches[0]],
            ["hmset", "expire"],
        )
        self.assertEqual(len(rdb.pipeline_batches), 1)
        self.assertIn(("hmset", "ws:hoga:005930", rdb.hashes["ws:hoga:005930"]), rdb.calls)
        self.assertEqual(rdb.expires, [("ws:hoga:005930", 120)])

    async def test_dedupe_skips_identical_hash_within_ttl(self):
        os.environ["WS_REDIS_DEDUPE_ENABLED"] = "1"
        rdb = FakeRedis()

        with patch("redis_writer._now_ms", side_effect=[1000, 1100, 1601]):
            await redis_writer.write_expected(rdb, {"10": "1000", "12": "1.0"}, "005930")
            await redis_writer.write_expected(rdb, {"10": "1000", "12": "1.0"}, "005930")
            await redis_writer.write_expected(rdb, {"10": "1000", "12": "1.0"}, "005930")

        hmset_calls = [call for call in rdb.calls if call[0] == "hmset" and call[1] == "ws:expected:005930"]
        self.assertEqual(len(hmset_calls), 2)

    async def test_heartbeat_is_not_suppressed(self):
        os.environ["WS_REDIS_PIPELINE_ENABLED"] = "1"
        os.environ["WS_REDIS_EXPIRE_THROTTLE_MS"] = "1000"
        os.environ["WS_REDIS_DEDUPE_ENABLED"] = "1"
        rdb = FakeRedis()

        await redis_writer.write_heartbeat(rdb, {"status": "ok"})
        await redis_writer.write_heartbeat(rdb, {"status": "ok"})

        heartbeat_expires = [item for item in rdb.expires if item == ("ws:py_heartbeat", 90)]
        heartbeat_sets = [item for item in rdb.sets if item[0] == "ws:heartbeat"]
        self.assertEqual(len(heartbeat_expires), 2)
        self.assertEqual(len(heartbeat_sets), 2)

    async def test_vi_watch_queue_is_not_suppressed(self):
        os.environ["WS_REDIS_PIPELINE_ENABLED"] = "1"
        os.environ["WS_REDIS_EXPIRE_THROTTLE_MS"] = "1000"
        os.environ["WS_REDIS_DEDUPE_ENABLED"] = "1"
        rdb = FakeRedis()

        with patch("redis_writer._now_ms", side_effect=[1000, 1100]):
            await redis_writer.write_vi(rdb, {"9001": "005930", "9068": "2", "1221": "1000"}, "005930")
            await redis_writer.write_vi(rdb, {"9001": "005930", "9068": "2", "1221": "1000"}, "005930")

        queue_pushes = [
            command
            for batch in rdb.pipeline_batches
            for command in batch
            if command[0] == "lpush" and command[1] == "vi_watch_queue"
        ]
        queue_expires = [item for item in rdb.expires if item == ("vi_watch_queue", 7200)]
        self.assertEqual(len(queue_pushes), 2)
        self.assertEqual(len(queue_expires), 2)

    async def test_strength_ltrim_and_lrange_sampling_are_throttled(self):
        os.environ["WS_REDIS_LTRIM_THROTTLE_MS"] = "1000"
        os.environ["WS_REDIS_STRENGTH_AVG_SAMPLE_EVERY"] = "3"
        rdb = FakeRedis()

        with patch("redis_writer._now_ms", side_effect=[1000, 1100]):
            await redis_writer.write_tick(rdb, {"228": "100"}, "005930")
            await redis_writer.write_tick(rdb, {"228": "110"}, "005930")

        self.assertEqual(rdb.ltrims, [("ws:strength:005930", 0, 9)])
        self.assertEqual(rdb.lranges, [])
        self.assertEqual(rdb.hashes["ws:strength_meta:005930"]["avg_5"], "105.0")
