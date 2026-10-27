"""SSH port-forward manager for SigmaOS-ssh-port-forward-plugin
(inspired by omarchy-port-forward-plugin).

Principles: plan-before-act (`start-plan` renders ssh commands but never
runs them), defensive spec parsing, fail-fast on duplicate bindings,
config store is a small auditable JSON file.
"""
import argparse, json, os, re, sys

ENGINE = {
    "name": "sigma-ssh-forward",
    "summary": "Manage SSH local/remote/dynamic port forwards",
    "language": "python",
    "verbs": ["add", "list", "start-plan", "stop", "test"],
    "principles": ["Plan Before Act", "Fail-Fast", "Defensive Programming",
                   "KISS", "Least Astonishment", "Deterministic Testing"],
}

cli_doc = """\
$ sigma-ssh-forward add "local 8080:web.internal:80" --via alice@bastion.example.com
$ sigma-ssh-forward list
local-8080  local  8080 -> web.internal:80  via alice@bastion.example.com  on
$ sigma-ssh-forward start-plan
ssh -N -L 8080:web.internal:80 alice@bastion.example.com
$ sigma-ssh-forward stop local-8080
$ sigma-ssh-forward test
ok: 1 forward(s) valid
"""

_TYPES = ("local", "remote", "dynamic")
_VIA_RE = re.compile(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+$")
_ID_RE = re.compile(r"^(local|remote|dynamic)-\d{1,5}$")


class ForwardError(ValueError):
    pass


def parse_spec(spec):
    """Parse e.g. 'local 8080:web.internal:80' or 'dynamic 1080'."""
    parts = spec.split()
    if len(parts) != 2 or parts[0] not in _TYPES:
        raise ForwardError(
            f"bad spec {spec!r}: expected 'TYPE LPORT[:RHOST:RPORT]' "
            f"with TYPE in {', '.join(_TYPES)}")
    ftype, binding = parts
    bits = binding.split(":")
    try:
        if ftype == "dynamic":
            if len(bits) != 1:
                raise ForwardError(
                    f"dynamic forwards take only LPORT: {spec!r}")
            lport, rhost, rport = int(bits[0]), None, None
        else:
            if len(bits) != 3:
                raise ForwardError(
                    f"{ftype} forwards need LPORT:RHOST:RPORT: {spec!r}")
            lport, rhost, rport = int(bits[0]), bits[1], int(bits[2])
    except ValueError as e:
        raise ForwardError(f"non-numeric port in {spec!r}") from e
    for p in (p for p in (lport, rport) if p is not None):
        if not 1 <= p <= 65535:
            raise ForwardError(f"port out of range in {spec!r}")
    if ftype != "dynamic" and (not rhost or " " in rhost):
        raise ForwardError(f"bad remote host in {spec!r}")
    return {"type": ftype, "lport": lport, "rhost": rhost, "rport": rport}


def load_store(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ForwardError(f"corrupt store {path!r}: expected a list")
    return data


def save_store(path, entries):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def add(path, spec, via):
    """Add a forward to the store. Fails on duplicates (fail-fast)."""
    if not _VIA_RE.match(via):
        raise ForwardError(f"--via must look like user@host, got {via!r}")
    fw = parse_spec(spec)
    entries = load_store(path)
    fid = f"{fw['type']}-{fw['lport']}"
    if not _ID_RE.match(fid):
        raise ForwardError(f"cannot derive forward id from {spec!r}")
    if any(e.get("id") == fid for e in entries):
        raise ForwardError(f"duplicate forward id: {fid}")
    if fw["type"] == "dynamic":
        fw["rhost"] = fw["rport"] = None
    fw.update({"id": fid, "via": via, "enabled": True})
    entries.append(fw)
    save_store(path, entries)
    return fw


def stop(path, fid):
    """Disable a forward (kept in store for audit, never deleted)."""
    if not _ID_RE.match(fid):
        raise ForwardError(f"bad forward id: {fid!r}")
    entries = load_store(path)
    for e in entries:
        if e.get("id") == fid:
            e["enabled"] = False
            save_store(path, entries)
            return e
    raise ForwardError(f"no such forward: {fid}")


def render(fw):
    """Render the ssh argv for one forward entry."""
    if fw["type"] == "dynamic":
        flag = f"-D {fw['lport']}"
    else:
        letter = "L" if fw["type"] == "local" else "R"
        flag = f"-{letter} {fw['lport']}:{fw['rhost']}:{fw['rport']}"
    return f"ssh -N {flag} {fw['via']}"


def start_plan(entries):
    """Pure plan: the exact commands a supervisor would run. No execution."""
    return [{"id": e["id"], "cmd": render(e)}
            for e in sorted(entries, key=lambda e: e["id"])
            if e.get("enabled")]


def test_store(entries):
    """Validate every stored forward; returns a list of error strings."""
    errors = []
    seen_bindings = {}
    for e in sorted(entries, key=lambda x: str(x.get("id"))):
        fid = e.get("id", "<no-id>")
        if not _ID_RE.match(str(fid)):
            errors.append(f"{fid}: malformed id")
            continue
        if e.get("type") not in _TYPES:
            errors.append(f"{fid}: bad type {e.get('type')!r}")
            continue
        lport = e.get("lport")
        if not isinstance(lport, int) or not 1 <= lport <= 65535:
            errors.append(f"{fid}: lport out of range: {lport!r}")
        if not _VIA_RE.match(str(e.get("via", ""))):
            errors.append(f"{fid}: bad via {e.get('via')!r}")
        if e["type"] in ("local", "remote"):
            rport = e.get("rport")
            if not isinstance(rport, int) or not 1 <= rport <= 65535:
                errors.append(f"{fid}: rport out of range: {rport!r}")
            if not e.get("rhost"):
                errors.append(f"{fid}: missing rhost")
        if e.get("enabled"):
            key = (e["type"], lport)
            if key in seen_bindings:
                errors.append(f"{fid}: duplicate binding with "
                              f"{seen_bindings[key]}")
            else:
                seen_bindings[key] = fid
    return errors


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=ENGINE["name"],
                                description=ENGINE["summary"])
    p.add_argument("--store",
                   default=os.path.expanduser(
                       "~/.config/sigma-ssh-forward/forwards.json"))
    sub = p.add_subparsers(dest="cmd", required=True)
    ad = sub.add_parser("add", help="add a forward to the store")
    ad.add_argument("spec", help="'local 8080:host:80' or 'dynamic 1080'")
    ad.add_argument("--via", required=True, help="user@ssh-host")
    sub.add_parser("list", help="list stored forwards")
    sub.add_parser("start-plan", help="print ssh commands for active forwards")
    st = sub.add_parser("stop", help="disable a forward")
    st.add_argument("id")
    sub.add_parser("test", help="validate the whole store")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "add":
            fw = add(args.store, args.spec, args.via)
            print(f"added {fw['id']} via {fw['via']}")
            return 0
        entries = load_store(args.store)
        if args.cmd == "list":
            if not entries:
                print("no forwards configured")
            for e in sorted(entries, key=lambda x: str(x.get("id"))):
                state = "on" if e.get("enabled") else "off"
                print(f"{e.get('id'):<14} {e.get('type'):<8} "
                      f"{e.get('lport')} -> "
                      f"{e.get('rhost') or '-'}:{e.get('rport') or '-'}  "
                      f"via {e.get('via')}  {state}")
        elif args.cmd == "start-plan":
            plan = start_plan(entries)
            if not plan:
                print("nothing to start", file=sys.stderr)
            for item in plan:
                print(item["cmd"])
        elif args.cmd == "stop":
            e = stop(args.store, args.id)
            print(f"stopped {e['id']} (kept in store, disabled)")
        elif args.cmd == "test":
            errors = test_store(entries)
            for err in errors:
                print(f"FAIL {err}")
            if errors:
                return 1
            print(f"ok: {len(entries)} forward(s) valid")
        return 0
    except (ForwardError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def self_test() -> None:
    # spec parsing
    fw = parse_spec("local 8080:web.internal:80")
    assert fw == {"type": "local", "lport": 8080, "rhost": "web.internal",
                  "rport": 80}
    assert parse_spec("dynamic 1080")["rhost"] is None
    for bad in ("local 8080", "local 8080:onlyhost", "dynamic 1080:1",
                "local 0:a:80", "local 70000:a:80", "tunnel 1:2:3",
                "local abc:web:80", "local 8080::"):
        try:
            parse_spec(bad)
        except ForwardError:
            pass
        else:
            raise AssertionError(f"spec accepted: {bad!r}")

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "forwards.json")
        assert load_store(store) == []          # missing store -> empty
        fw1 = add(store, "local 8080:web.internal:80", "alice@bastion.example.com")
        add(store, "dynamic 1080", "alice@bastion.example.com")
        entries = load_store(store)
        assert [e["id"] for e in entries] == ["local-8080", "dynamic-1080"]

        try:
            add(store, "local 8080:other:90", "alice@bastion.example.com")
        except ForwardError:
            pass
        else:
            raise AssertionError("duplicate id accepted")
        try:
            add(store, "local 1:2:3", "root")
        except ForwardError:
            pass
        else:
            raise AssertionError("bad via accepted")

        plan = start_plan(entries)
        assert [p["cmd"] for p in plan] == [
            "ssh -N -D 1080 alice@bastion.example.com",
            "ssh -N -L 8080:web.internal:80 alice@bastion.example.com",
        ]
        assert test_store(entries) == []

        stop(store, "local-8080")
        entries = load_store(store)
        assert [p["cmd"] for p in start_plan(entries)] == \
            ["ssh -N -D 1080 alice@bastion.example.com"]
        try:
            stop(store, "nope-1")
        except ForwardError:
            pass
        else:
            raise AssertionError("bad id accepted")

        # corrupt entries are caught by test_store, not by rendering
        entries.append({"id": "local-99999", "type": "local", "lport": 99999,
                        "rhost": None, "rport": None, "via": "!!",
                        "enabled": True})
        errors = test_store(entries)
        assert any("lport out of range" in e for e in errors)
        assert any("bad via" in e for e in errors)
        assert any("missing rhost" in e for e in errors)

        save_store(store, entries + [dict(entries[1], id="dynamic-1080")])
        assert any("duplicate binding" in e
                   for e in test_store(load_store(store)))

        with open(os.path.join(d, "corrupt.json"), "w") as fh:
            fh.write('{"not": "a list"}')
        try:
            load_store(os.path.join(d, "corrupt.json"))
        except ForwardError:
            pass
        else:
            raise AssertionError("corrupt store accepted")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
