"""Object storage for uploaded document files.

Replaces direct local-filesystem writes in routes.py with an S3-compatible
backend.  Every stored object is keyed as:

    {org_id}/{data_source_id}/{filename}

No object may be written without an `org_id` prefix — omitting it raises
TypeError at call time (no default value), mirroring the same requirement in
VectorStore.search() and VectorStore.ingest_chunks().

Configuration (all via environment / .env):
    OBJECT_STORAGE_BACKEND   "s3" | "local" (default: "local" for dev)
    AWS_S3_BUCKET            S3 bucket name (required when backend=s3)
    AWS_REGION               AWS region (default: us-east-1)
    AWS_ACCESS_KEY_ID        }  Standard boto3 env vars — not read
    AWS_SECRET_ACCESS_KEY    }  directly here; boto3 picks them up.
    OBJECT_STORAGE_LOCAL_DIR Local root dir when backend=local (default: ./data/object_store)

For local dev with MinIO, set AWS_S3_BUCKET and point AWS_ENDPOINT_URL at
your MinIO instance — boto3's S3 client respects AWS_ENDPOINT_URL as the
service endpoint without any code changes here.
"""

import io
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def store_document(
    org_id: str,          # required — no default
    data_source_id: str,  # required — no default
    filename: str,
    file_bytes: bytes,
) -> str:
    """Write file_bytes to object storage and return the storage URI.

    URI format:
      - S3 backend:    s3://{bucket}/{org_id}/{data_source_id}/{filename}
      - Local backend: file://{abs_path}/{org_id}/{data_source_id}/{filename}

    The returned URI is what should be stored in documents.storage_uri
    (Phase 2 schema).
    """
    key = _build_key(org_id, data_source_id, filename)
    backend = _get_backend()

    if backend == "s3":
        return _s3_put(key, file_bytes)
    else:
        return _local_put(key, file_bytes)


def retrieve_document(
    org_id: str,
    data_source_id: str,
    filename: str,
) -> bytes:
    """Read and return the raw bytes for a previously stored document."""
    key = _build_key(org_id, data_source_id, filename)
    backend = _get_backend()

    if backend == "s3":
        return _s3_get(key)
    else:
        return _local_get(key)


def delete_document(
    org_id: str,
    data_source_id: str,
    filename: str,
) -> None:
    """Delete a single document from object storage."""
    key = _build_key(org_id, data_source_id, filename)
    backend = _get_backend()

    if backend == "s3":
        _s3_delete(key)
    else:
        _local_delete(key)


def delete_org_prefix(org_id: str) -> int:
    """Delete every object under the org_id/ prefix.

    Used by Phase 6 cascading org deletion (task 6.2).  Returns the count of
    deleted objects.
    """
    backend = _get_backend()
    if backend == "s3":
        return _s3_delete_prefix(f"{org_id}/")
    else:
        return _local_delete_prefix(f"{org_id}/")


def storage_uri_for(
    org_id: str,
    data_source_id: str,
    filename: str,
) -> str:
    """Return the URI a document would have without writing anything.

    Useful for assertions in tests (e.g. test_storage_keys_are_org_prefixed).
    """
    key = _build_key(org_id, data_source_id, filename)
    backend = _get_backend()
    if backend == "s3":
        bucket = _s3_bucket()
        return f"s3://{bucket}/{key}"
    else:
        root = _local_root()
        return f"file://{(root / key).resolve()}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_key(org_id: str, data_source_id: str, filename: str) -> str:
    """Build the storage key.  The org_id prefix is the isolation boundary."""
    # Sanitise the filename component only — org_id and data_source_id are
    # trusted internal values (UUIDs from the DB), not user-supplied strings.
    safe_filename = Path(filename).name  # strips any path traversal
    return f"{org_id}/{data_source_id}/{safe_filename}"


def _get_backend() -> str:
    return os.environ.get("OBJECT_STORAGE_BACKEND", "local").lower()


# ---------------------------------------------------------------------------
# S3 backend
# ---------------------------------------------------------------------------

def _s3_client():
    import boto3  # lazy import — not in requirements.txt until task 4.5 wires it
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _s3_bucket() -> str:
    bucket = os.environ.get("AWS_S3_BUCKET")
    if not bucket:
        raise EnvironmentError("AWS_S3_BUCKET must be set when OBJECT_STORAGE_BACKEND=s3")
    return bucket


def _s3_put(key: str, data: bytes) -> str:
    client = _s3_client()
    bucket = _s3_bucket()
    client.put_object(Bucket=bucket, Key=key, Body=data)
    return f"s3://{bucket}/{key}"


def _s3_get(key: str) -> bytes:
    client = _s3_client()
    response = client.get_object(Bucket=_s3_bucket(), Key=key)
    return response["Body"].read()


def _s3_delete(key: str) -> None:
    client = _s3_client()
    client.delete_object(Bucket=_s3_bucket(), Key=key)


def _s3_delete_prefix(prefix: str) -> int:
    client = _s3_client()
    bucket = _s3_bucket()
    deleted = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects = page.get("Contents", [])
        if not objects:
            continue
        client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
        )
        deleted += len(objects)
    return deleted


# ---------------------------------------------------------------------------
# Local filesystem backend (dev / CI without real S3)
# ---------------------------------------------------------------------------

def _local_root() -> Path:
    root = Path(os.environ.get("OBJECT_STORAGE_LOCAL_DIR", "./data/object_store"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _local_put(key: str, data: bytes) -> str:
    target = _local_root() / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return f"file://{target.resolve()}"


def _local_get(key: str) -> bytes:
    target = _local_root() / key
    if not target.exists():
        raise FileNotFoundError(f"Object not found: {key}")
    return target.read_bytes()


def _local_delete(key: str) -> None:
    target = _local_root() / key
    if target.exists():
        target.unlink()


def _local_delete_prefix(prefix: str) -> int:
    root = _local_root()
    prefix_path = root / prefix
    if not prefix_path.exists():
        return 0
    deleted = 0
    for p in prefix_path.rglob("*"):
        if p.is_file():
            p.unlink()
            deleted += 1
    # Clean up empty directories left behind
    for p in sorted(prefix_path.rglob("*"), reverse=True):
        if p.is_dir():
            try:
                p.rmdir()  # only removes if empty
            except OSError:
                pass
    try:
        prefix_path.rmdir()
    except OSError:
        pass
    return deleted