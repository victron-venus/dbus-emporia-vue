# Changelog

## 1.0.4

- Handle SIGTERM and SIGINT by cancelling and joining the main workers instead of raising SystemExit in an unobserved task.
- Bound WebSocket close, release every channel's private D-Bus connection, and remove signal handlers even when cleanup fails.
- Test real process signals with stubbed network and D-Bus I/O, including cleanup failure paths.

## 1.0.3

- Prevent an older initial HA snapshot from overwriting an interleaved state-trigger update.
- Prefer explicit HA state timestamps when both are available; otherwise retain the received event, including unavailable power and measured zero.
- Keep timestamp comparison local to initialization and preserve the existing connection deadline, message cap, and reconnect policy.
- Test older/newer snapshot ordering, absent timestamps, initial-query failure, and installation from arbitrarily named worktrees.
