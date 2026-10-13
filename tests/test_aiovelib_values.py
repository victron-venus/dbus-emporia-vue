"""Check the real vendored D-Bus value layer in a process without test stubs."""

import subprocess
import sys
from pathlib import Path


def test_variant_encoding_and_cached_service_values():
    # Orchestration tests replace dbus_fast in sys.modules. The child uses the
    # installed transport and the checked-in library, with no live bus required.
    script = r"""
import sys
sys.path.insert(0, "aiovelib")
from aiovelib.client import Item, Service, make_variant, servicetype
from dbus_fast import Variant

cases = [
    (None, "ai", []), (False, "b", False), (1.25, "d", 1.25),
    (42, "i", 42), (2**40, "x", 2**40), ("label", "s", "label"),
    ([], "ai", []), ([1, 2], "ai", [1, 2]),
    ([1.5, 2], "ad", [1.5, 2]), (["a", "b"], "as", ["a", "b"]),
    (["not", 1], "ai", []),
]
for value, signature, expected in cases:
    result = make_variant(value)
    assert result.signature == signature
    assert result.value == expected

item = Item()
assert not item.seen and item.value is None
item.update_unseen(11)
item.update_unseen(3)  # A delayed scan must not overwrite a newer signal.
assert item.seen and item.value == 11
item.update([])
assert item.seen and item.value is None

service = Service(None, "com.victronenergy.acload.fixture", ":1.1")
service.paths = {"/Ac/Power"}
assert not service.seen("/Ac/Power") and service.get_value("/Ac/Power") is None
assert servicetype(service.name) == "com.victronenergy.acload"
changed = service.update_items({
    "/Ac/Power": {"Value": Variant("i", 21)},
    "/Unwatched": {"Value": Variant("i", 99)},
})
assert changed == {"/Ac/Power": 21}
assert service.get_value("/Ac/Power") == 21 and service.seen("/Ac/Power")
assert service.get_value("/Unwatched") is None
assert service.update_items({"/Ac/Power": {"Text": Variant("s", "21 W")}}) == {}
service.update_unseen_items({"/Ac/Power": {"Value": Variant("i", 1)}})
assert service.get_value("/Ac/Power") == 21
service.update_items({"/Ac/Power": {"Value": Variant("ai", [])}})
assert service.get_value("/Ac/Power") is None
print("REAL_VALUE_LAYER_OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_VALUE_LAYER_OK" in result.stdout
