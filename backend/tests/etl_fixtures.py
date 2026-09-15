"""Builds throwaway SQLite databases shaped like the two source systems.

These mirror the real columns of each project's `users` table closely enough to exercise
every branch of the ETL, including the identity-conflict paths.
"""
from __future__ import annotations

import json
import sqlite3

TATWAMASI_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY, uuid TEXT, username TEXT UNIQUE, display_name TEXT,
    email TEXT UNIQUE, hashed_password TEXT, bio TEXT, photo_url TEXT, location TEXT,
    is_verified INTEGER DEFAULT 0, reputation_score REAL DEFAULT 100.0,
    followers_count INTEGER DEFAULT 0, following_count INTEGER DEFAULT 0,
    posts_count INTEGER DEFAULT 0, streak INTEGER DEFAULT 0
);
CREATE TABLE posts (
    id INTEGER PRIMARY KEY, user_id INTEGER, content TEXT, media_urls TEXT,
    likes_count INTEGER DEFAULT 0, comments_count INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE reels (
    id INTEGER PRIMARY KEY, user_id INTEGER, video_url TEXT, caption TEXT,
    hashtags TEXT, likes_count INTEGER DEFAULT 0, comments_count INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE tweets (
    id INTEGER PRIMARY KEY, user_id INTEGER, content TEXT,
    likes_count INTEGER DEFAULT 0, comments_count INTEGER DEFAULT 0, created_at TEXT
);
"""

LABOURLINK_SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY, phone TEXT UNIQUE, email TEXT, password_hash TEXT,
    full_name TEXT, avatar_url TEXT, user_type TEXT, is_verified INTEGER DEFAULT 0,
    reputation_score NUMERIC DEFAULT 50.00
);
CREATE TABLE categories (
    id INTEGER PRIMARY KEY, name TEXT, slug TEXT, description TEXT,
    base_fare NUMERIC, per_km_rate NUMERIC, per_minute_rate NUMERIC,
    urgency_multiplier NUMERIC, night_multiplier NUMERIC
);
CREATE TABLE laborers (
    user_id INTEGER PRIMARY KEY, category_id INTEGER, hourly_rate NUMERIC,
    rating NUMERIC DEFAULT 5.0, total_jobs INTEGER DEFAULT 0,
    verification_tier TEXT DEFAULT 'bronze', background_check_status TEXT,
    approved_at TEXT, bio TEXT, skills TEXT, avg_response_time_seconds INTEGER
);
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY, customer_id INTEGER, laborer_id INTEGER, category_id INTEGER,
    status TEXT, urgency TEXT, pickup_location TEXT, job_details TEXT, fare_breakdown TEXT,
    photos TEXT, payment_status TEXT, created_at TEXT, completed_at TEXT
);
CREATE TABLE reviews (
    id INTEGER PRIMARY KEY, job_id INTEGER, reviewer_id INTEGER, reviewee_id INTEGER,
    rating INTEGER, punctuality INTEGER, quality INTEGER, communication INTEGER,
    comment TEXT, created_at TEXT
);
"""


def build_tatwamasi(path: str, *, orphan_post: bool = False) -> None:
    """Three social users: one that overlaps LabourLink by email, two unique.

    ``orphan_post`` adds a post whose author does not exist. It is off by default so the
    fixture represents a *clean* migration that should commit; the FK-abort test opts in.
    """
    conn = sqlite3.connect(path)
    conn.executescript(TATWAMASI_SCHEMA)
    conn.executemany(
        "INSERT INTO users (id, uuid, username, display_name, email, hashed_password, bio,"
        " photo_url, location, is_verified, reputation_score, followers_count, following_count,"
        " posts_count, streak) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            # This email also exists in LabourLink -> must MERGE.
            (1, "u-1", "priya", "Priya Malviya", "priya@example.com",
             "$argon2id$v=19$m=65536,t=3,p=4$abc$xyz", "Loves design", "https://cdn/a.jpg",
             "Indore", 1, 140.0, 512, 88, 34, 12),
            (2, "u-2", "arjun", "Arjun Rao", "arjun@example.com",
             "$argon2id$v=19$m=65536,t=3,p=4$abc$xyz", "", None, "Bhopal", 0, 90.0, 40, 120, 8, 0),
            # No email at all -> clean create.
            (3, "u-3", "meera", "Meera Nair", None,
             "$argon2id$v=19$m=65536,t=3,p=4$abc$xyz", "", None, None, 0, 60.0, 3, 4, 1, 0),
        ],
    )
    conn.executemany(
        "INSERT INTO posts (id, user_id, content, media_urls, likes_count, comments_count, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        [
            (10, 1, "First post #indore", json.dumps(["https://cdn/p1.jpg"]), 12, 3, "2026-01-05T10:00:00"),
            (11, 2, "Hello world", json.dumps([]), 1, 0, "2026-01-06T10:00:00"),
            # Orphan: author 99 does not exist -> must be counted as unresolved.
            *([(12, 99, "Orphaned post", json.dumps([]), 0, 0, "2026-01-07T10:00:00")]
              if orphan_post else []),
        ],
    )
    conn.executemany(
        "INSERT INTO reels (id, user_id, video_url, caption, hashtags, likes_count, comments_count, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        [(20, 1, "https://cdn/r1.mp4", "Sunset", json.dumps(["sunset"]), 40, 5, "2026-02-01T10:00:00")],
    )
    conn.executemany(
        "INSERT INTO tweets (id, user_id, content, likes_count, comments_count, created_at)"
        " VALUES (?,?,?,?,?,?)",
        [(30, 2, "short thought", 2, 0, "2026-02-02T10:00:00")],
    )
    conn.commit()
    conn.close()


def build_labourlink(path: str) -> None:
    """Customer 1 shares an email with Tatwamasi user 1; worker 2 is unique."""
    conn = sqlite3.connect(path)
    conn.executescript(LABOURLINK_SCHEMA)
    conn.executemany(
        "INSERT INTO users (id, phone, email, password_hash, full_name, avatar_url, user_type,"
        " is_verified, reputation_score) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            # Same email as Tatwamasi user 1 -> MERGE. bcrypt hash must be detected.
            (1, "+919876500001", "priya@example.com", "$2b$12$abcdefghijklmnopqrstuv",
             "Priya M.", "https://cdn/p-ll.jpg", "customer", 1, 82.00),
            (2, "+919876500002", "ramesh@example.com", "$2b$12$abcdefghijklmnopqrstuv",
             "Ramesh Kumar", None, "laborer", 1, 91.50),
            # Same email as Tatwamasi user 2 -> merges on email. Labour Link has no
            # password for him, so the merge must adopt Tatwamasi's real hash.
            (3, "+919876500003", "arjun@example.com", None, "Arjun R.", None, "customer", 0, 55.00),
            # Unique, and genuinely password-less everywhere -> must get an unusable hash.
            (4, "+919876500004", "otp-only@example.com", None, "OTP Only", None, "customer", 0, 50.00),
        ],
    )
    conn.executemany(
        "INSERT INTO categories (id, name, slug, description, base_fare, per_km_rate,"
        " per_minute_rate, urgency_multiplier, night_multiplier) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (1, "Electrical", "electrical", "Wiring and fittings", 200, 18, 6, 1.25, 1.15),
            (2, "Plumbing", "plumbing", "Leaks and motors", 200, 18, 5, 1.25, 1.15),
        ],
    )
    conn.executemany(
        "INSERT INTO laborers (user_id, category_id, hourly_rate, rating, total_jobs,"
        " verification_tier, background_check_status, approved_at, bio, skills,"
        " avg_response_time_seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(2, 1, 380, 4.9, 48, "gold", "cleared", "2026-01-01T09:00:00",
          "12 years residential", json.dumps(["Wiring", "Inverter"]), 300)],
    )
    conn.executemany(
        "INSERT INTO jobs (id, customer_id, laborer_id, category_id, status, urgency,"
        " pickup_location, job_details, fare_breakdown, photos, payment_status, created_at,"
        " completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(50, 1, 2, 1, "completed", "standard",
          json.dumps({"lat": 22.7196, "lng": 75.8577, "address": "Vijay Nagar"}),
          json.dumps({"title": "Rewire flat", "description": "Full replacement"}),
          json.dumps({"total": 1846.21, "platform_fee": 240.81}),
          json.dumps([]), "paid", "2026-03-01T08:00:00", "2026-03-01T14:00:00")],
    )
    conn.executemany(
        "INSERT INTO reviews (id, job_id, reviewer_id, reviewee_id, rating, punctuality,"
        " quality, communication, comment, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(70, 50, 1, 2, 5, 5, 5, 4, "On time, clean work.", "2026-03-01T15:00:00")],
    )
    conn.commit()
    conn.close()
