"""Live journey for the auth session, the karma ledger and the feed cursor.

Why this exists next to the test suite rather than inside it: the suite runs the app in-process
against a database built by `init_db()`, with the cache port swapped for a dict. These three
guarantees are the ones that only exist at the seams -- a revoked token must be refused by the
*running* dependency, an exoneration must survive the migrated schema's index, and a cursor must
page a feed that real rows are being added to. Driving them over HTTP against a booted server is
the difference between "the function is correct" and "the product is correct".

    KARMA_BASE=http://localhost:8000/api/v1 PYTHONPATH=. python scripts/live_session_and_ledger_journey.py

Needs a seeded database (``python seed.py``) for the customer / worker / admin it signs in as:
`priya`, `ramesh.electric`, `karma.admin`, password `StrongPass!234`. Everything it creates is
fresh per run -- a gig, a dispute, three feed posts -- so it is safe to re-run against the same
server, and it deliberately never writes to the database. It spends about six logins per run,
against a server that allows ten a minute per address, hence the memo below: a journey that
could not be run twice would not be a smoke test.

Exits non-zero if any check fails, so it can be used as a smoke test.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("KARMA_BASE", "http://localhost:8000/api/v1").rstrip("/")
PASSWORD = "StrongPass!234"

CUSTOMER = "priya"
WORKER = "ramesh.electric"
ADMIN = "karma.admin"

_failures: list[str] = []


def _check(label: str, condition: bool, detail: str = "") -> None:
    mark = "\u2713" if condition else "\u2717"
    print(f"  {mark}  {label}{(' -> ' + detail) if detail else ''}")
    if not condition:
        _failures.append(label)


def _http(
    method: str, path: str, body: dict | None = None, token: str | None = None
) -> tuple[int, dict | list]:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": raw.decode(errors="replace")}


_SESSIONS: dict[str, dict] = {}


def _login(handle: str) -> dict:
    """Sign in, once per account per run.

    `/auth/login` is budgeted per address (10 a minute) and the point of a live journey is that it
    can be run against a shared staging server without tripping the guard the suite simulates. Two
    sections need the same three seeded accounts, so the pair is memoised -- and the section that
    *destroys* sessions deliberately does not use it, because its whole job is to make tokens dead.
    """
    if handle not in _SESSIONS:
        _SESSIONS[handle] = _sign_in(handle)
    return _SESSIONS[handle]


def _sign_in(handle: str) -> dict:
    """An actual round trip: the memoised `_login` is what sections should call.

    A 429 is not a failure of the product, it is the product: `/auth/login` is budgeted per
    address, and running this journey twice inside a minute spends it. So wait for the window and
    try once more rather than reporting a broken server -- and see the count in the docstring for
    how close a single run comes to that budget.
    """
    status, body = _http("POST", "/auth/login", {"identifier": handle, "password": PASSWORD})
    if status == 429:
        print("       login budget exhausted for this address; waiting out the window")
        time.sleep(62)
        status, body = _http("POST", "/auth/login", {"identifier": handle, "password": PASSWORD})
    if status != 200 or not isinstance(body, dict) or "access_token" not in body:
        raise SystemExit(
            f"login {handle!r} failed ({status}): {body}. This journey needs a seeded database "
            "-- run `python seed.py` against the database the server is using."
        )
    return body


def _detail(body: dict | list, key: str) -> str:
    if isinstance(body, dict) and key in body:
        return str(body[key])[:90]
    return str(body)[:90]


def _ledger(user_id: int) -> dict:
    """The *public* ledger route, called with no token on purpose.

    `/karma/ledger/{id}` is readable without a session by design (a hiring card has to cite where
    a number came from), so a journey that authenticated here would not be proving that.
    """
    status, body = _http("GET", f"/karma/ledger/{user_id}")
    if status != 200 or not isinstance(body, dict):
        raise SystemExit(f"public ledger for user {user_id} is not anonymously readable: {status} {body}")
    return body


def _rows(ledger: dict) -> list[tuple[str, int]]:
    return [(event["event_type"], event["delta"]) for event in ledger["events"]]


def _register_or_login(handle: str) -> dict:
    """A fresh account if the server has never seen this one, its login if it has.

    Ending sessions is the one part of this journey that is destructive, so it does not get
    practised on a seeded account: `logout-all` on `priya` would also end whatever a person is
    doing in the browser right now, on exactly the server this script is pointed at.
    """
    status, body = _http(
        "POST",
        "/auth/register",
        {
            "handle": handle,
            "display_name": handle.replace(".", " ").title(),
            "email": f"{handle}@example.com",
            "password": PASSWORD,
        },
    )
    if status == 201 and isinstance(body, dict):
        return body
    if status not in (409, 422):  # 422 = the email already exists, which is the same situation
        raise SystemExit(f"could not create {handle!r} ({status}): {str(body)[:160]}")
    return _sign_in(handle)


def sessions() -> None:
    print("\nsessions \u2014 a logout the server can see")
    phone = _register_or_login("journey.device")
    laptop = _sign_in("journey.device")  # a second device, the same account
    admin = _login(ADMIN)

    def me(token: str) -> int:
        return _http("GET", "/auth/me", token=token)[0]

    _check("two devices, one account, both live", me(phone["access_token"]) == 200 and me(laptop["access_token"]) == 200)

    status, body = _http(
        "POST",
        "/auth/logout",
        {"refresh_token": phone["refresh_token"]},
        token=phone["access_token"],
    )
    _check("POST /auth/logout is accepted", status == 200, _detail(body, "detail"))
    status, body = _http("GET", "/auth/me", token=phone["access_token"])
    _check(
        "that device's access token is refused, and says why",
        status == 401 and _detail(body, "detail") == "Token revoked",
        f"{status} {_detail(body, 'detail')}",
    )
    status, _ = _http("POST", "/auth/refresh", {"refresh_token": phone["refresh_token"]})
    _check("and its refresh token cannot mint a replacement", status == 401, str(status))
    _check(
        "the other device is untouched (one device's sign-out is not the account's)",
        me(laptop["access_token"]) == 200,
    )

    status, body = _http("POST", "/auth/logout-all", token=laptop["access_token"])
    _check("POST /auth/logout-all is accepted", status == 200, _detail(body, "detail"))
    for label, token in (("laptop", laptop["access_token"]), ("phone", phone["access_token"])):
        status, body = _http("GET", "/auth/me", token=token)
        _check(
            f"the epoch ends the {label} too, in its own words",
            status == 401 and _detail(body, "detail") == "Session ended; sign in again",
            f"{status} {_detail(body, 'detail')}",
        )
    _check(
        "a different account survives someone else's panic button",
        me(admin["access_token"]) == 200,
    )
    fresh = _sign_in("journey.device")
    _check(
        "it ends sessions without locking the account: re-login works, old tokens stay dead",
        me(fresh["access_token"]) == 200 and me(laptop["access_token"]) == 401,
    )


def ledger() -> None:
    print("\nledger \u2014 an accusation bites, a dismissal gives it back")
    customer, worker, admin = _login(CUSTOMER), _login(WORKER), _login(ADMIN)

    profile_status, profile = _http("GET", "/workers/me/profile", token=worker["access_token"])
    if profile_status != 200 or not isinstance(profile, dict):
        raise SystemExit(f"the seeded worker has no profile ({profile_status}); run `python seed.py`")

    # Hire them in the trade they actually serve: `/gigs/{id}/assign` refuses a worker whose
    # profile is in another category, and taking `categories[0]` would be an accident of ordering.
    status, categories = _http("GET", "/categories", token=customer["access_token"])
    if status != 200 or not isinstance(categories, list) or not categories:
        raise SystemExit(f"no categories to hire against ({status}); the database is not seeded")
    assert isinstance(categories, list)
    wanted = profile.get("category")
    matches = [c for c in categories if c.get("name") == wanted]
    if not matches:
        raise SystemExit(f"seeded categories do not include {wanted!r}")
    category_id = matches[0]["id"]
    me_status, me = _http("GET", "/auth/me", token=worker["access_token"])
    worker_id = me["id"] if me_status == 200 and isinstance(me, dict) else None
    _check(
        "the seeded worker is available to be hired",
        profile.get("is_available") is True and bool(worker_id),
        f"{profile.get('category')} at \u20b9{profile.get('hourly_rate')}/h, "
        f"tier {profile.get('verification_tier')}",
    )

    # Reaching this line at all is the anonymity check: `_ledger` sends no Authorization header.
    before = _ledger(int(worker_id))
    print(f"       baseline, read anonymously: blended {before['blended']}, band {before['band']}")

    status, gig = _http(
        "POST",
        "/gigs",
        {
            "category_id": category_id,
            "title": "Regrind the distribution board",
            "lat": 22.7196,
            "lng": 75.8577,
        },
        token=customer["access_token"],
    )
    if status != 201 or not isinstance(gig, dict):
        raise SystemExit(f"could not post a gig ({status}): {gig}")
    gig_id = gig["id"]
    status, assigned = _http(
        "POST", f"/gigs/{gig_id}/assign?worker_id={worker_id}", token=customer["access_token"]
    )
    if status != 200 or not isinstance(assigned, dict) or assigned.get("status") != "assigned":
        # Everything below depends on a worker being on the gig: a dispute filed against a gig
        # with nobody assigned records no penalty, so the ledger checks would fail for the wrong
        # reason. A missing prerequisite is a hard stop, not a failed assertion.
        raise SystemExit(f"could not hire the worker onto gig {gig_id} ({status}): {assigned}")
    _check("the gig hired a real worker", True, f"gig {gig_id} -> assigned")

    status, body = _http(
        "POST",
        f"/gigs/{gig_id}/dispute",
        {"reason": "Quoted \u20b94,000, then demanded more at the door."},
        token=customer["access_token"],
    )
    _check("a dispute was filed against them", status == 201, _detail(body, "detail"))

    accused = _ledger(int(worker_id))
    _check(
        "the penalty lands immediately, before anyone investigates",
        accused["work"] < before["work"],
        f"work {before['work']} -> {accused['work']}, blended {before['blended']} -> {accused['blended']}",
    )

    status, disputes = _http("GET", "/admin/disputes", token=admin["access_token"])
    mine = [
        d for d in (disputes if isinstance(disputes, list) else []) if d.get("gig_id") == gig_id
    ]
    if not mine:
        raise SystemExit(f"the new dispute is not visible to the trust desk: {disputes}")
    dispute_id = mine[0]["id"]

    status, body = _http(
        "PATCH",
        f"/admin/disputes/{dispute_id}",
        {"status": "dismissed"},
        token=admin["access_token"],
    )
    _check(
        "the dismissal reports the reversal",
        status == 200 and "karma restored" in _detail(body, "detail"),
        _detail(body, "detail"),
    )

    after = _ledger(int(worker_id))
    _check(
        "the number is exactly where the accusation found it",
        after["work"] == before["work"] and after["blended"] == before["blended"],
        f"work {accused['work']} -> {after['work']}, blended {accused['blended']} -> {after['blended']}",
    )
    rows = _rows(after)
    _check(
        "history is appended, never edited: both halves are on the record",
        ("dispute_filed", -15) in rows and ("case_dismissed", 15) in rows,
        str([r for r in rows if r[0] in {"dispute_filed", "case_dismissed"}]),
    )
    labels = {event["event_type"]: event["reason"] for event in after["events"]}
    _check(
        "the public ledger labels the exoneration instead of publishing prose",
        labels.get("case_dismissed") == "Case dismissed",
        repr(labels.get("case_dismissed")),
    )
    _check(
        "and the accusation's text does not leak to strangers",
        "4,000" not in json.dumps(after, ensure_ascii=False),
    )

    status, body = _http(
        "PATCH",
        f"/admin/disputes/{dispute_id}",
        {"status": "dismissed"},
        token=admin["access_token"],
    )
    again = _ledger(int(worker_id))
    # `total_events` is the unpaginated row count, which is what makes this check true on a
    # database this journey has already run against: the *page* of events would show reversals
    # from earlier runs and could not answer "was a row appended just now?".
    _check(
        "a retried dismissal is accepted, and appends nothing",
        status == 200
        and "karma restored" not in _detail(body, "detail")
        and again["total_events"] == after["total_events"]
        and again["work"] == after["work"],
        f"{after['total_events']} events -> {again['total_events']}, work held at {again['work']}",
    )
    _check(
        "the count above is the ledger's own row count, not a page artefact",
        again["truncated"] is True or again["total_events"] == len(again["events"]),
        f"{len(again['events'])} of {again['total_events']} shown, truncated={again['truncated']}",
    )


def feed() -> None:
    print("\nfeed \u2014 the cursor, not an offset")
    worker = _login(WORKER)
    token = worker["access_token"]

    ids = []
    for n in (1, 2, 3):
        status, post = _http("POST", "/feed/posts", {"kind": "pulse", "body": f"Journey pulse {n}"}, token=token)
        if status != 201 or not isinstance(post, dict):
            raise SystemExit(f"could not publish a pulse ({status}): {post}")
        ids.append(post["id"])

    status, page1 = _http("GET", "/feed/posts?limit=2", token=token)
    assert isinstance(page1, list)
    first = [p["id"] for p in page1]
    _check("page one is the newest two, newest first", first == [ids[2], ids[1]], str(first))

    status, page2 = _http("GET", f"/feed/posts?limit=2&before_id={first[-1]}", token=token)
    assert isinstance(page2, list)
    second = [p["id"] for p in page2]
    _check("page two starts where page one stopped", ids[0] in second and first[-1] not in second, str(second))

    # The property that makes it a cursor: a post at the head must not shift what page two holds.
    status, late = _http("POST", "/feed/posts", {"kind": "pulse", "body": "Late entry"}, token=token)
    assert isinstance(late, dict)
    status, again = _http("GET", f"/feed/posts?limit=2&before_id={first[-1]}", token=token)
    assert isinstance(again, list)
    _check(
        "a post landing at the head while page two is in flight shifts nothing",
        [p["id"] for p in again] == second,
        f"{second} stayed {str([p['id'] for p in again])} (newest is now {late.get('id')})",
    )
    _http("DELETE", f"/feed/posts/{late['id']}", token=token)


def main() -> int:
    for name in ("sessions", "ledger", "feed"):
        try:
            globals()[name]()
        except SystemExit as exc:  # a missing prerequisite is a hard stop, not a check failure
            print(f"\n  ! {name} could not run: {exc}")
            return 2
    if _failures:
        print(f"\n{len(_failures)} check(s) failed: " + ", ".join(_failures))
        return 1
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
