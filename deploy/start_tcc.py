"""One worker, no migrations, no secret-valued arguments, explicit trusted proxy."""
import ipaddress
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]


def trusted_proxies(raw):
    parts = raw.split(",")
    if not raw or any(not part.strip() or part.strip() == "*" for part in parts):
        raise ValueError("EXPLICIT_TRUSTED_PROXY_ADDRESSES_REQUIRED")
    for part in parts:
        network = ipaddress.ip_network(part.strip(), strict=False)
        if network.prefixlen == 0:
            raise ValueError("GENERIC_PROXY_TRUST_FORBIDDEN")
    return ",".join(p.strip() for p in parts)


def main():
    try:
        proxies = trusted_proxies(os.environ.get("SIGRA_TRUSTED_PROXY_IPS", ""))
        manifest = json.loads((ROOT / "release/manifest.json").read_text(encoding="utf-8"))
        version = manifest["release_id"]
        if os.environ.get("SIGRA_SYSTEM_VERSION", version) != version:
            raise ValueError("SYSTEM_VERSION_DIFFERS_FROM_RELEASE")
        os.environ["SIGRA_SYSTEM_VERSION"] = version
        os.environ["SIGRA_RELEASE_MANIFEST_FILE"] = str(ROOT / "release/manifest.json")
        from app.deployment import settings
        settings()  # Refuse before Uvicorn opens a port.
        import uvicorn
        uvicorn.run("app.deployment:create_app", factory=True, host="0.0.0.0",
                    port=int(os.environ.get("PORT", "10000")), workers=1,
                    proxy_headers=True, forwarded_allow_ips=proxies, access_log=False)
    except Exception as error:
        # No raw exception messages, URLs, file contents, request bodies or secrets.
        from app.deployment import DeploymentBlocked
        code = error.code if isinstance(error, DeploymentBlocked) else "DEPLOY_START_BLOCKED"
        print(json.dumps({"status": "DEPLOY_START_BLOCKED", "code": code, "secret_values_reported": False}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
