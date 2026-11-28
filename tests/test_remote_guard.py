from remote.guard import Guard


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_rate_limit_allows_20_then_refuses_within_10_minutes():
    clock = Clock()
    guard = Guard(clock=clock)
    assert all(guard.allow_command() for _ in range(20))
    assert guard.allow_command() is False
    clock.now += 601
    assert guard.allow_command() is True


def test_rate_window_boundary_is_exactly_600_seconds():
    clock = Clock()
    guard = Guard(clock=clock)
    assert all(guard.allow_command() for _ in range(20))
    clock.now += 599
    assert guard.allow_command() is False
    clock.now += 1
    assert guard.allow_command() is True


def test_a_flood_gets_one_notice_per_30_seconds_with_the_count_it_dropped():
    clock = Clock()
    guard = Guard(clock=clock)
    for _ in range(20):
        guard.allow_command()
    assert guard.drop() == 1
    assert [guard.drop() for _ in range(4)] == [0, 0, 0, 0]
    assert guard.dropped_to_announce() == 0
    clock.now += 30
    assert guard.dropped_to_announce() == 4
    assert guard.dropped_to_announce() == 0
    assert guard.drop() == 0


def test_commands_dropped_before_a_disarm_are_not_announced_after_it():
    clock = Clock()
    guard = Guard(clock=clock)
    guard.arm()
    for _ in range(20):
        guard.allow_command()
    guard.drop()
    for _ in range(3):
        guard.drop()
    guard.disarm()
    clock.now += 60
    guard.arm()
    assert guard.dropped_to_announce() == 0


def test_the_epoch_moves_only_when_an_armed_guard_is_disarmed():
    guard = Guard()
    guard.disarm()
    assert guard.epoch == 0
    guard.arm()
    guard.arm()
    assert guard.epoch == 0
    guard.disarm()
    guard.disarm()
    assert guard.epoch == 1


def test_disarm_and_rearm():
    guard = Guard(clock=Clock())
    guard.arm()
    guard.disarm()
    assert guard.armed is False
    guard.arm()
    assert guard.armed is True


def test_stop_all_runs_every_registered_stop_and_disarms():
    guard = Guard(clock=Clock())
    guard.arm()
    stopped = []
    guard.register_stop("a", lambda: stopped.append("a"))
    guard.register_stop("b", lambda: stopped.append("b"))
    guard.stop_all()
    assert sorted(stopped) == ["a", "b"]
    assert guard.armed is False


def test_stop_all_survives_a_failing_stop():
    guard = Guard(clock=Clock())
    stopped = []

    def boom():
        raise RuntimeError("x")

    guard.register_stop("bad", boom)
    guard.register_stop("good", lambda: stopped.append("good"))
    guard.stop_all()
    assert stopped == ["good"]
