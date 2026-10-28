"""Thin psycopg helpers. Every call uses parameters, never string formatting of values."""
from contextlib import contextmanager

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from . import config


@contextmanager
def connect():
    try:
        conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row, connect_timeout=3)
    except psycopg.OperationalError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    with conn:
        yield conn


def rows(sql, params=None):
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


def row(sql, params=None):
    with connect() as conn:
        return conn.execute(sql, params).fetchone()


def run(sql, params=None):
    with connect() as conn:
        return conn.execute(sql, params).rowcount
