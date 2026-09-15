"""Static verification of the production Compose stack.

The runtime smoke test (``smoke.sh``) needs a Docker daemon. This script needs only the
backend virtualenv, so it can run anywhere — including the environments that cannot start
containers — and it fails the same way both gates do: non-zero exit, one line per check.

    cd backend && .venv/bin/python ../tools/compose_smoke/check_static.py

What it proves without a daemon:
  * the compose file parses and is wired as documented (one published port, API internal,
    health-gated startup order, the ten required variables, hardened api service);
  * both build contexts exist and every COPY source is present, both images run unprivileged,
    the entrypoint passes ``sh -n`` and the Alembic chain has a single head;
  * nginx proxies ``/api/`` to the API with WebSocket upgrade headers and a body cap that
    admits the 5 MiB upload limit;
  * the production settings guard actually fails closed: every documented misconfiguration
    is constructed for real and must refuse, and one complete environment must boot.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        f"PyYAML is required ({exc}); use the backend virtualenv: cd backend && .venv/bin/python ../tools/compose_smoke/check_static.py"
    ) from exc

BACKEND = Path(__file__).resolve().parents[2] / "backend"
STOCK = Path(__file__).resolve().parents[2]
COMPOSE = STOCK / "docker-compose.yml"

REQUIRED_VARS = {
    "POSTGRES_PASSWORD",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "SECRET_KEY",
    "ALLOWED_ORIGINS",
    "TRUSTED_HOSTS",
    "GEOCODING_USER_AGENT",
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
}

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "✓" if condition else "✗"
    print(f"  {mark}  {label}{(' -> ' + detail) if detail else ''}")
    if not condition:
        _failures.append(label)


def main() -> None:
    print("compose wiring")
    raw = COMPOSE.read_text()
    compose = yaml.safe_load(raw)
    services = compose["services"]
    check(
        "services are db, redis, storage, api, web",
        set(services) == {"db", "redis", "storage", "api", "web"},
        str(sorted(services)),
    )
    check(
        "db is PostgreSQL 17 with PostGIS",
        services["db"]["image"] == "postgis/postgis:17-3.5",
        services["db"]["image"],
    )
    api, web = services["api"], services["web"]
    check("api and web build from the two in-repo contexts", api["build"] == "./backend" and web["build"] == "./frontend")
    published = [(name, svc.get("ports")) for name, svc in services.items() if svc.get("ports")]
    check(
        "exactly one published port, on web, mapping the container's 8080",
        len(published) == 1 and published[0][0] == "web" and published[0][1] == [f"${{WEB_PORT:-8080}}:8080"],
        str(published),
    )
    depends = api["depends_on"]
    check(
        "api starts only after healthy db and redis, and after storage starts",
        depends.get("db", {}).get("condition") == "service_healthy"
        and depends.get("redis", {}).get("condition") == "service_healthy"
        and depends.get("storage", {}).get("condition") == "service_started",
    )
    check("web starts after api", "api" in web["depends_on"])
    check(
        "api service is hardened (read-only rootfs, no privilege escalation, tmpfs /tmp)",
        api.get("read_only") is True
        and "no-new-privileges:true" in api.get("security_opt", [])
        and "/tmp" in api.get("tmpfs", []),
    )
    found_vars = set(re.findall(r"\$\{([A-Z0-9_]+):\?", raw))
    check(
        "every required variable is declared with :? (fail-fast), no undeclared extras",
        found_vars == REQUIRED_VARS,
        str(sorted(found_vars ^ REQUIRED_VARS)) if found_vars != REQUIRED_VARS else "",
    )

    print("build contexts")
    for context, dockerfile in (("backend", BACKEND), ("frontend", STOCK / "frontend")):
        path = dockerfile / "Dockerfile"
        check(f"{context}: Dockerfile exists", path.is_file())
        if not path.is_file():
            continue
        text = path.read_text()
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("COPY") or "--from=" in stripped:
                continue
            sources = stripped.split()[1:-1]  # everything but the destination
            missing = [s for s in sources if not (dockerfile / s).exists()]
            check(f"{context}: COPY sources exist ({', '.join(sources)})", not missing, str(missing))
        check(f"{context}: image runs unprivileged", re.search(r"^USER (?!root)\S+", text, re.M) is not None)

    entrypoint = BACKEND / "docker-entrypoint.sh"
    probe = subprocess.run(["sh", "-n", str(entrypoint)], capture_output=True, text=True)
    check("entrypoint passes sh -n", probe.returncode == 0, probe.stderr.strip()[:120])

    heads = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
    )
    head_lines = [l for l in heads.stdout.splitlines() if l.strip()]
    check("Alembic chain has exactly one head", len(head_lines) == 1, " ".join(head_lines))

    print("nginx reverse proxy")
    nginx = (STOCK / "frontend" / "nginx.conf").read_text()
    check("listens on 8080 (no privileged port, matches EXPOSE and compose)", "listen       8080;" in nginx)
    check("proxies /api/ to the internal API host", "proxy_pass http://api:8000;" in nginx)
    check(
        "passes the WebSocket upgrade handshake through",
        "proxy_set_header Upgrade $http_upgrade;" in nginx and 'proxy_set_header Connection "upgrade";' in nginx,
    )
    check("body cap admits the 5 MiB upload limit plus multipart framing", "client_max_body_size 6m;" in nginx)

    print("production settings guard (executed)")
    from app.core.config import DEFAULT_SECRET, Settings

    valid = dict(
        ENVIRONMENT="production",
        SECRET_KEY="smoke-test-secret-0123456789-0123456789-0123",
        ALLOWED_ORIGINS='["https://karma.example.com"]',
        TRUSTED_HOSTS='["karma.example.com"]',
        DATABASE_URL="postgresql+asyncpg://karma:secret@db:5432/karma",
        REDIS_URL="redis://redis:6379/0",
        OBJECT_STORAGE_BACKEND="s3",
        S3_ENDPOINT="http://storage:8333",
        S3_ACCESS_KEY="smoke-access-key",
        S3_SECRET_KEY="smoke-secret-key",
        GEOCODING_PROVIDER="nominatim",
        GEOCODING_USER_AGENT="KARMA-compose-smoke/1.0 ops@example.com",
        PAYMENT_PROVIDER="stripe",
        STRIPE_SECRET_KEY="sk_test_smoke",
        STRIPE_PUBLISHABLE_KEY="pk_test_smoke",
        STRIPE_WEBHOOK_SECRET="whsec_smoke",
    )
    try:
        good = Settings(_env_file=None, **valid)
        check(
            "a complete production environment passes the guard",
            good.is_production and good.use_postgis,
        )
    except RuntimeError as exc:
        check("a complete production environment passes the guard", False, str(exc))

    broken = {
        "default SECRET_KEY": {"SECRET_KEY": DEFAULT_SECRET},
        "wildcard ALLOWED_ORIGINS": {"ALLOWED_ORIGINS": '["*"]'},
        "wildcard TRUSTED_HOSTS": {"TRUSTED_HOSTS": '["*"]'},
        "missing REDIS_URL": {"REDIS_URL": None},
        "local object storage in production": {"OBJECT_STORAGE_BACKEND": "local"},
        "missing S3 credentials": {"S3_ACCESS_KEY": None, "S3_SECRET_KEY": None},
        "disabled geocoder": {"GEOCODING_PROVIDER": "disabled"},
        "unidentified geocoder agent": {"GEOCODING_USER_AGENT": "KARMA-development/1.0"},
        "simulated payments": {"PAYMENT_PROVIDER": "simulated"},
        "missing Stripe secret": {"STRIPE_SECRET_KEY": None},
        "malformed Stripe publishable key": {"STRIPE_PUBLISHABLE_KEY": "not-a-key"},
        "missing webhook secret": {"STRIPE_WEBHOOK_SECRET": None},
    }
    for label, overrides in broken.items():
        env = {**valid, **overrides}
        try:
            Settings(_env_file=None, **env)
            check(f"guard refuses: {label}", False, "settings constructed")
        except RuntimeError:
            check(f"guard refuses: {label}", True)
        except Exception as exc:  # noqa: BLE001 - a crash is not a refusal
            check(f"guard refuses: {label}", False, f"raised {type(exc).__name__}: {exc}")

    print()
    if _failures:
        print(f"{len(_failures)} check(s) FAILED:")
        for label in _failures:
            print(f"  ✗  {label}")
        raise SystemExit(1)
    print("static Compose verification: all checks passed")


if __name__ == "__main__":
    sys.path.insert(0, str(BACKEND))
    main()
