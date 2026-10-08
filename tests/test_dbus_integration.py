"""Exercise real D-Bus in child processes, isolated from orchestration test stubs."""

import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]


def _daemon_binary():
    for candidate in ("dbus-daemon", "/opt/homebrew/bin/dbus-daemon", "/usr/local/bin/dbus-daemon"):
        binary = shutil.which(candidate)
        if binary:
            return binary
    if os.environ.get("CI"):
        pytest.fail("The CI integration tests require dbus-daemon")
    pytest.skip("Install dbus-daemon to run the private-bus integration tests")


@pytest.mark.parametrize(
    "case",
    [
        "name_collision",
        "daemon_loss",
        "client_disconnect",
        "clean_shutdown",
        "invalid_ha_url",
        "connect_failure",
        "constructor_failure",
    ],
)
def test_private_dbus_lifecycle(case):
    # test_main deliberately replaces aiovelib and dbus_fast in sys.modules;
    # a fresh interpreter ensures these tests use the actual transport/library.
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), case, _daemon_binary()],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PRIVATE_DBUS_OK" in result.stdout
    assert "Future exception was never retrieved" not in result.stderr
    assert "Task exception was never retrieved" not in result.stderr
    assert "Task was destroyed" not in result.stderr


async def _name_collision(address):
    from dbus_fast import Message, MessageType
    from dbus_fast.aio import MessageBus

    from main import AcLoadService

    first_bus = await MessageBus(bus_address=address).connect()
    second_bus = await MessageBus(bus_address=address).connect()
    name = "com.victronenergy.acload.private_test"
    first = AcLoadService(first_bus, name, 71, "Existing owner", 0)
    second = AcLoadService(second_bus, name, 72, "Rejected owner", 0)
    try:
        await first.register()
        await first.register()  # Re-registering an already-owned name is valid.
        with pytest.raises(RuntimeError, match=r"D-Bus name .* is unavailable"):
            await second.register()
        first.update_power(11)
        result = await second_bus.call(
            Message(
                destination=name,
                path="/Ac/Power",
                interface="com.victronenergy.BusItem",
                member="GetValue",
            )
        )
        assert result.body[0].value == 11
        await first.close()
        # A rejected applicant must not silently inherit the name later.
        owner = await second_bus.call(
            Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="GetNameOwner",
                signature="s",
                body=[name],
            )
        )
        assert owner.message_type == MessageType.ERROR
        assert owner.error_name == "org.freedesktop.DBus.Error.NameHasNoOwner"
    finally:
        await first.close()
        await second.close()


async def _main_lifecycle(address, daemon, case):
    from dbus_fast.aio import MessageBus

    import main

    buses = []
    ready = asyncio.Event()
    heartbeat_writes = []
    config = {
        "log_level": "ERROR",
        "ha_token": "private-test-placeholder",
        "channels": [
            {
                "ha_entity_id": f"sensor.audit_{index}",
                "service_name": f"com.victronenergy.acload.private_test_{index}",
                "instance": 71 + index,
                "custom_name": f"Private test {index}",
            }
            for index in range(2)
        ],
    }

    def bus_factory(**kwargs):
        bus = MessageBus(bus_address=address)
        buses.append(bus)
        return bus

    async def idle_source(client):
        for service in client.channel_map.values():
            service.update_entity(
                {
                    "state": "100",
                    "attributes": {"unit_of_measurement": "W"},
                    "last_reported": datetime.now(UTC).isoformat(),
                }
            )
        ready.set()
        # No new sample is needed to notice loss of the publication transport.
        await asyncio.Event().wait()

    with (
        patch.object(main, "load_config", return_value=config),
        patch.object(main, "MessageBus", side_effect=bus_factory),
        patch.object(main, "run_websocket_client", side_effect=idle_source),
        patch.object(main, "write_heartbeat", side_effect=lambda: heartbeat_writes.append(1)),
    ):
        task = asyncio.create_task(main.main())
        try:
            await asyncio.wait_for(ready.wait(), timeout=3)
            assert len(buses) == 2
            if case == "daemon_loss":
                daemon.terminate()
                await asyncio.to_thread(daemon.wait, timeout=3)
            elif case == "client_disconnect":
                buses[0].disconnect()
            if case == "clean_shutdown":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=3)
            else:
                with pytest.raises(ConnectionError, match="D-Bus connection lost for"):
                    await asyncio.wait_for(task, timeout=3)
            assert all(not bus.connected for bus in buses)
            writes_at_shutdown = len(heartbeat_writes)
            await asyncio.sleep(0)
            assert len(heartbeat_writes) == writes_at_shutdown
            assert not [
                pending
                for pending in asyncio.all_tasks()
                if pending is not asyncio.current_task() and not pending.done()
            ]
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


async def _startup_failure(address, case):
    from dbus_fast import Message, MessageType
    from dbus_fast.aio import MessageBus

    import main

    buses = []
    names = [f"com.victronenergy.acload.private_test_{index}" for index in range(2)]
    config = {
        "ha_url": "invalid://example.test/api/websocket"
        if case == "invalid_ha_url"
        else "ws://example.test/api/websocket",
        "ha_token": "private-test-placeholder",
        "channels": [
            {
                "ha_entity_id": f"sensor.audit_{index}",
                "service_name": name,
                "instance": 71 + index,
                "custom_name": f"Private test {index}",
            }
            for index, name in enumerate(names)
        ],
    }

    class FailingBus(MessageBus):
        async def connect(self):
            await super().connect()
            if case == "connect_failure" and len(buses) == 2:
                # Exercise cleanup even if authentication connected the socket
                # before a later startup phase raised.
                raise RuntimeError("injected connection failure")
            return self

    def bus_factory(**kwargs):
        bus = FailingBus(bus_address=address)
        buses.append(bus)
        return bus

    service_class = main.AcLoadService

    def service_factory(*args):
        if case == "constructor_failure" and len(buses) == 2:
            raise RuntimeError("injected constructor failure")
        return service_class(*args)

    expected = ValueError if case == "invalid_ha_url" else RuntimeError
    with (
        patch.object(main, "load_config", return_value=config),
        patch.object(main, "MessageBus", side_effect=bus_factory),
        patch.object(main, "AcLoadService", side_effect=service_factory),
    ):
        operation = main.main()
        with pytest.raises(expected):
            await asyncio.wait_for(operation, timeout=3)
    assert len(buses) == 2
    assert all(not bus.connected for bus in buses)
    observer = await MessageBus(bus_address=address).connect()
    try:
        for name in names:
            result = await observer.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="GetNameOwner",
                    signature="s",
                    body=[name],
                )
            )
            assert result.message_type == MessageType.ERROR
            assert result.error_name == "org.freedesktop.DBus.Error.NameHasNoOwner"
    finally:
        observer.disconnect()
        await observer.wait_for_disconnect()
    assert not [
        pending
        for pending in asyncio.all_tasks()
        if pending is not asyncio.current_task() and not pending.done()
    ]


def _run_child(case, binary):
    sys.path.insert(0, str(REPOSITORY))
    # An explicit temporary Unix socket also avoids macOS launchd's session bus.
    daemon = subprocess.Popen(
        [binary, "--session", "--address=unix:tmpdir=/tmp", "--nofork", "--print-address=1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        address = daemon.stdout.readline().strip()
        assert address, daemon.stderr.read()
        if case == "name_collision":
            asyncio.run(_name_collision(address))
        elif case in {"invalid_ha_url", "connect_failure", "constructor_failure"}:
            asyncio.run(_startup_failure(address, case))
        else:
            asyncio.run(_main_lifecycle(address, daemon, case))
        print("PRIVATE_DBUS_OK")
    finally:
        if daemon.poll() is None:
            daemon.terminate()
            daemon.wait(timeout=3)
        daemon.stdout.close()
        daemon.stderr.close()


if __name__ == "__main__":
    _run_child(sys.argv[1], sys.argv[2])
