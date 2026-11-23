import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from limits.base import BoundarySearch, Built, SingleRequest  # noqa: E402
from limits.protocols import OpenAICompat  # noqa: E402
from limits.transport import HttpResult  # noqa: E402


class FakeContext:
    """Accepts values <= limit; optionally simulates a transport failure."""

    def __init__(self, limit: float, transient_at: float | None = None):
        self.limit = limit
        self.transient_at = transient_at
        self.calls: list[float] = []

    def send(self, protocol, built: Built, max_tokens: int) -> HttpResult:
        value = float(built.body)
        self.calls.append(value)
        if self.transient_at is not None and value >= self.transient_at:
            return HttpResult(status=0, elapsed_s=0.0, error="timeout")
        if value <= self.limit:
            return HttpResult(
                status=200,
                elapsed_s=0.01,
                payload={"usage": {"prompt_tokens": int(value)}},
            )
        return HttpResult(
            status=400,
            elapsed_s=0.01,
            payload={"error": {"code": "Exceeded", "message": "too large"}},
        )


def search(limit: float, transient_at: float | None = None, **kwargs) -> BoundarySearch:
    return BoundarySearch(
        id="probe_x",
        suite="unit",
        title="probe",
        protocol=OpenAICompat(),
        expect="n/a",
        builder=lambda value: Built(body=f"{value}".encode(), meta={}),
        points=[10, 40, 60],
        axis="mb",
        axis_unit="MB",
        tolerance=5,
        max_refine=6,
        **kwargs,
    )


class BoundarySearchTests(unittest.TestCase):
    def test_brackets_the_limit_within_tolerance(self):
        context = FakeContext(limit=50)
        result = search(50).run(context)
        boundary = result.boundary
        self.assertIsNotNone(boundary)
        self.assertLessEqual(boundary.last_ok, 50)
        self.assertGreater(boundary.first_fail, 50)
        self.assertLessEqual(boundary.first_fail - boundary.last_ok, 5)
        self.assertIn(60, context.calls, "ladder must reach the first failing point")
        self.assertLessEqual(max(context.calls), 60, "must not probe beyond the ladder top")

    def test_stops_at_first_failure_during_ladder(self):
        context = FakeContext(limit=30)
        result = search(30).run(context)
        self.assertNotIn(60, [r.axis_value for r in result.records])

    def test_transient_failure_yields_no_boundary(self):
        context = FakeContext(limit=100, transient_at=60)
        result = search(100, transient_at=60).run(context)
        self.assertIsNone(result.boundary)
        self.assertEqual(result.records[-1].status, 0)
        self.assertIn("传输层异常", result.records[-1].note)

    def test_all_pass_yields_no_boundary(self):
        result = search(1000).run(FakeContext(1000))
        self.assertIsNone(result.boundary)

    def test_transient_can_be_treated_as_limit(self):
        """网关用「断开连接」表达超限时，该失败应计入边界。"""
        result = search(100, transient_at=60, transient_is_failure=True).run(
            FakeContext(100, transient_at=60)
        )
        self.assertIsNotNone(result.boundary)
        self.assertEqual(result.boundary.first_fail, 60)
        failure = next(r for r in result.records if r.axis_value == 60)
        self.assertIn("按超限处理", failure.note)

    def test_refine_respects_max_steps(self):
        context = FakeContext(limit=37)
        experiment = search(37)
        experiment.max_refine = 1
        experiment.run(context)
        self.assertLessEqual(len(context.calls), 5)


class SingleRequestTests(unittest.TestCase):
    def test_emits_one_record(self):
        experiment = SingleRequest(
            id="one",
            suite="unit",
            title="one",
            protocol=OpenAICompat(),
            expect="200",
            builder=lambda: Built(body=b"1", meta={"image_count": 0}),
        )
        result = experiment.run(FakeContext(limit=10))
        self.assertEqual(len(result.records), 1)
        self.assertTrue(result.records[0].accepted)

    def test_rejection_captures_error(self):
        experiment = SingleRequest(
            id="one",
            suite="unit",
            title="one",
            protocol=OpenAICompat(),
            expect="400",
            builder=lambda: Built(body=b"999", meta={}),
        )
        record = experiment.run(FakeContext(limit=10)).records[0]
        self.assertFalse(record.accepted)
        self.assertEqual(record.error_code, "Exceeded")
        self.assertEqual(record.error_message, "too large")


if __name__ == "__main__":
    unittest.main()
