#!/usr/bin/env python3
"""Measure the real installed join library in the disposable domain lab.

Run as root with --backend realmd|winbind and --output <json>.
The requested domain is reserved .invalid, so there is no domain membership.
This script intentionally exercises real service and PAM changes on the OLD
package. Never run it on a user's workstation or on either existing demo VM.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--backend", required=True, choices=("realmd", "winbind"))
parser.add_argument("--output", required=True)
args = parser.parse_args()
assert os.geteuid() == 0
assert socket.gethostname() == "pardus-domain-lab"
assert Path("/root/domain-validation-lab").is_file()

env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
# Use an explicit baseline opposite to the requested backend, before measuring.
subprocess.run(["systemctl", "disable", "--now", "sssd", "winbind"], check=True)
previous = "winbind" if args.backend == "realmd" else "sssd"
subprocess.run(["systemctl", "enable", previous], check=True)
subprocess.run(["pam-auth-update", "--disable" if args.backend == "realmd" else "--enable", "sss"],
               env=env, check=True)

def state():
    paths = [Path("/etc/hostname"), Path("/etc/hosts"), Path("/etc/nsswitch.conf"),
             Path("/etc/krb5.conf"), Path("/etc/krb5.conf.old"),
             Path("/etc/sssd/sssd.conf"), Path("/etc/samba/smb.conf")]
    paths += sorted(Path("/etc/pam.d").glob("common-*"))
    paths += sorted(Path("/var/lib/pam").glob("*"))
    backup_dir = Path("/usr/share/pardus_domain_joiner/backups")
    if backup_dir.exists():
        paths += sorted(p for p in backup_dir.rglob("*") if p.is_file())
    files = {}
    for path in paths:
        if path.is_file():
            stat = path.stat()
            files[str(path)] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "mode": oct(stat.st_mode & 0o7777), "uid": stat.st_uid, "gid": stat.st_gid,
            }
        else:
            files[str(path)] = None
    services = {}
    for service in ("sssd", "winbind"):
        services[service] = {
            "enabled": subprocess.run(["systemctl", "is-enabled", service], capture_output=True,
                                      text=True).stdout.strip(),
            "active": subprocess.run(["systemctl", "is-active", service], capture_output=True,
                                     text=True).stdout.strip(),
        }
    return {"files": files, "services": services, "hostname": socket.gethostname()}

from pardus_domain_joiner import domain_operations

before = state()
error = domain_operations.join(
    "pardus-domain-lab", "missing.pdj.invalid", "test-user", "not-a-real-password",
    ouaddress="computers", workgroup="EXAMPLE",
    realmd=args.backend == "realmd", winbind=args.backend == "winbind",
)
after = state()
changed_files = [p for p in sorted(before["files"].keys() | after["files"].keys())
                 if before["files"].get(p) != after["files"].get(p)]
result = {
    "backend": args.backend,
    "library_path": domain_operations.__file__,
    "library_sha256": hashlib.sha256(Path(domain_operations.__file__).read_bytes()).hexdigest(),
    "error": error,
    "before": before, "after": after,
    "changed_files": changed_files,
    "services_changed": before["services"] != after["services"],
    "preserved": before == after,
}
Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({k: result[k] for k in ("backend", "error", "changed_files",
                                       "services_changed", "preserved")}, ensure_ascii=False, indent=2))
