"""
CSV connector — reads contact records from local files or S3-compatible storage.

Supports:
  - Local filesystem glob patterns
  - S3-compatible bucket pulls (when s3_endpoint_url is configured)
  - Configurable field mapping
  - Schema validation and quarantine
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from workers.connectors.base import BaseConnector, ConnectorRecord

logger = structlog.get_logger(__name__)

# Required fields in a CSV row
_REQUIRED_FIELDS = {"email"}

# Optional field name aliases (csv_col -> canonical_name)
_FIELD_MAP = {
    "email_address": "email",
    "mail": "email",
    "first name": "first_name",
    "firstname": "first_name",
    "last name": "last_name",
    "lastname": "last_name",
    "title": "job_title",
    "jobtitle": "job_title",
    "job title": "job_title",
    "company name": "company",
    "organization": "company",
    "website": "domain",
    "company domain": "domain",
}


def _normalize_headers(row: dict) -> dict:
    """Lower-case and map header aliases to canonical names."""
    out = {}
    for k, v in row.items():
        canonical = _FIELD_MAP.get(k.lower().strip(), k.lower().strip())
        out[canonical] = v
    return out


class CSVConnector(BaseConnector):
    """
    Connector that reads contacts from local CSV files.
    Files are discovered by glob pattern from source_dir.
    """

    schema_version = 1

    def __init__(self, source_dir: str | Path, glob_pattern: str = "**/*.csv"):
        super().__init__(connector_id=f"csv:{source_dir}")
        self.source_dir = Path(source_dir)
        self.glob_pattern = glob_pattern

    def fetch(self, watermark: str | None) -> list[dict]:
        """Read all CSV files in source_dir. watermark is ignored for file-based ingestion."""
        files = sorted(self.source_dir.glob(self.glob_pattern))
        if not files:
            logger.warning("csv_no_files_found", source_dir=str(self.source_dir))
            return []

        logger.info("csv_files_found", count=len(files))
        records = []
        for fpath in files:
            try:
                with fpath.open(encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        records.append({**_normalize_headers(row), "_source_file": fpath.name})
            except Exception as exc:
                logger.error("csv_file_read_error", path=str(fpath), error=str(exc))

        logger.info("csv_records_read", total=len(records))
        return records

    def normalize(self, raw_record: dict) -> ConnectorRecord | None:
        email = raw_record.get("email", "").lower().strip()
        if not email or "@" not in email:
            logger.debug("csv_invalid_email", email=email)
            return None

        source_id = raw_record.get("id") or raw_record.get("contact_id") or email

        return ConnectorRecord(
            source_system="csv",
            source_record_id=str(source_id),
            operation=raw_record.get("operation", "insert"),
            event_time=_parse_date(raw_record.get("event_time") or raw_record.get("created_at")),
            schema_version=self.schema_version,
            raw_payload={k: v for k, v in raw_record.items() if not k.startswith("_")},
            trace_id=str(uuid.uuid4()),
        )


class S3CSVConnector(BaseConnector):
    """
    Connector that reads CSV files from an S3-compatible bucket.
    Requires boto3 and S3 credentials in environment.
    """

    schema_version = 1

    def __init__(self, bucket: str, prefix: str = "raw/", connector_id: str | None = None):
        super().__init__(connector_id=connector_id or f"s3:{bucket}/{prefix}")
        self.bucket = bucket
        self.prefix = prefix

    def _s3_client(self):
        import boto3
        from app.config import get_settings
        s = get_settings()
        kwargs: dict[str, Any] = {}
        if s.s3_endpoint_url:
            kwargs["endpoint_url"] = s.s3_endpoint_url
        if s.s3_access_key_id:
            kwargs["aws_access_key_id"] = s.s3_access_key_id
            kwargs["aws_secret_access_key"] = s.s3_secret_access_key
        return boto3.client("s3", region_name=s.s3_region, **kwargs)

    def fetch(self, watermark: str | None) -> list[dict]:
        s3 = self._s3_client()
        paginator = s3.get_paginator("list_objects_v2")
        records = []

        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".csv"):
                    continue
                if watermark and obj["LastModified"].isoformat() <= watermark:
                    continue

                resp = s3.get_object(Bucket=self.bucket, Key=key)
                content = resp["Body"].read().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(content))
                for row in reader:
                    records.append({**_normalize_headers(row), "_source_key": key})

        return records

    def normalize(self, raw_record: dict) -> ConnectorRecord | None:
        email = raw_record.get("email", "").lower().strip()
        if not email or "@" not in email:
            return None

        source_id = raw_record.get("id") or email
        return ConnectorRecord(
            source_system="s3_csv",
            source_record_id=str(source_id),
            operation="insert",
            event_time=_parse_date(raw_record.get("created_at")),
            schema_version=self.schema_version,
            raw_payload={k: v for k, v in raw_record.items() if not k.startswith("_")},
            trace_id=str(uuid.uuid4()),
        )

    def _extract_watermark(self, records: list[dict]) -> str | None:
        timestamps = [r.get("_last_modified") for r in records if r.get("_last_modified")]
        return max(timestamps) if timestamps else None


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
