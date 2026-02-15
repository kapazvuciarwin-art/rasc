#!/usr/bin/env python3
"""SQLite storage helpers for sensor readings."""

import sqlite3


def get_db(database_path):
    """獲取資料庫連接"""
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(database_path):
    """初始化資料庫"""
    conn = get_db(database_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            co2_ppm INTEGER,
            temperature_c REAL,
            humidity REAL,
            raw_data TEXT,
            rssi INTEGER,
            cpu_usage_percent REAL,
            ram_usage_percent REAL,
            cpu_temp_c REAL
        )
    """
    )
    existing_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(readings)").fetchall()
    }
    if "cpu_usage_percent" not in existing_cols:
        conn.execute("ALTER TABLE readings ADD COLUMN cpu_usage_percent REAL")
    if "ram_usage_percent" not in existing_cols:
        conn.execute("ALTER TABLE readings ADD COLUMN ram_usage_percent REAL")
    if "cpu_temp_c" not in existing_cols:
        conn.execute("ALTER TABLE readings ADD COLUMN cpu_temp_c REAL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON readings(timestamp)")
    conn.commit()
    conn.close()


def save_reading(database_path, now_iso, **kwargs):
    """儲存讀數到資料庫"""
    conn = get_db(database_path)
    conn.execute(
        """
        INSERT INTO readings (
            timestamp, co2_ppm, temperature_c, humidity, raw_data, rssi,
            cpu_usage_percent, ram_usage_percent, cpu_temp_c
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            now_iso,
            kwargs.get("co2_ppm"),
            kwargs.get("temperature_c"),
            kwargs.get("humidity"),
            kwargs.get("raw_data"),
            kwargs.get("rssi"),
            kwargs.get("cpu_usage_percent"),
            kwargs.get("ram_usage_percent"),
            kwargs.get("cpu_temp_c"),
        ),
    )
    conn.commit()
    conn.close()


def fetch_history(database_path, since_iso, max_points):
    """取得歷史資料，必要時在 SQL 端抽樣"""
    conn = get_db(database_path)
    if max_points > 0:
        total_count = conn.execute(
            "SELECT COUNT(*) AS count FROM readings WHERE timestamp >= ?",
            (since_iso,),
        ).fetchone()["count"]
        if total_count > max_points:
            step = max(1, total_count // max_points)
            rows = conn.execute(
                """
                SELECT
                    timestamp, co2_ppm, temperature_c, humidity, rssi,
                    cpu_usage_percent, ram_usage_percent, cpu_temp_c
                FROM (
                    SELECT
                        timestamp, co2_ppm, temperature_c, humidity, rssi,
                        cpu_usage_percent, ram_usage_percent, cpu_temp_c,
                        ROW_NUMBER() OVER (ORDER BY timestamp ASC) AS rn
                    FROM readings
                    WHERE timestamp >= ?
                )
                WHERE (rn - 1) % ? = 0
                ORDER BY timestamp ASC
                LIMIT ?
            """,
                (since_iso, step, max_points),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    timestamp, co2_ppm, temperature_c, humidity, rssi,
                    cpu_usage_percent, ram_usage_percent, cpu_temp_c
                FROM readings
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
            """,
                (since_iso,),
            ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT
                timestamp, co2_ppm, temperature_c, humidity, rssi,
                cpu_usage_percent, ram_usage_percent, cpu_temp_c
            FROM readings
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
        """,
            (since_iso,),
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def fetch_stats_24h(database_path, since_iso):
    """取得 24 小時統計"""
    conn = get_db(database_path)
    stats = conn.execute(
        """
        SELECT
            COUNT(*) as count,
            AVG(co2_ppm) as avg_co2,
            MIN(co2_ppm) as min_co2,
            MAX(co2_ppm) as max_co2,
            AVG(temperature_c) as avg_temp,
            MIN(temperature_c) as min_temp,
            MAX(temperature_c) as max_temp
        FROM readings
        WHERE timestamp >= ?
    """,
        (since_iso,),
    ).fetchone()
    conn.close()
    return dict(stats)

