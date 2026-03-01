"""S3 state store.

Stores session state as JSON objects in S3 with optional namespace prefix::

    s3://{bucket}/{prefix}/sessions/{session_id}/state.json

When prefix is None, the path collapses to::

    s3://{bucket}/sessions/{session_id}/state.json

Uses ``anyio.to_thread.run_sync`` to run boto3 calls in the thread pool,
matching the same async pattern as LocalStateStore.
"""

from __future__ import annotations

from functools import partial
from typing import Any

import boto3
from anyio import to_thread
from botocore.config import Config

from netherbrain.agent_runtime.models.session import SessionState


def _create_s3_client(
    endpoint_url: str,
    access_key: str,
    secret_key: str,
    region: str | None = None,
    path_style: bool = False,
) -> Any:
    """Create a boto3 S3 client.

    Args:
        endpoint_url: S3 endpoint URL.
        access_key: AWS access key ID.
        secret_key: AWS secret access key.
        region: AWS region name (optional, some endpoints require it).
        path_style: Use path-style addressing instead of virtual-hosted.
            Required by MinIO and some S3-compatible services.
    """
    config = Config(
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
        s3={"addressing_style": "path" if path_style else "auto"},
    )

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=config,
    )


class S3StateStore:
    """S3 implementation of the StateStore protocol.

    Layout::

        s3://{bucket}/{key_prefix}sessions/{session_id}/state.json

    Where ``key_prefix`` is ``{prefix}/`` if prefix is set, or empty string.
    """

    def __init__(
        self,
        bucket: str,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        prefix: str | None = None,
        region: str | None = None,
        path_style: bool = False,
    ) -> None:
        self._bucket = bucket
        self._client = _create_s3_client(endpoint_url, access_key, secret_key, region=region, path_style=path_style)
        self._key_prefix = f"{prefix}/sessions/" if prefix else "sessions/"

    def _object_key(self, session_id: str) -> str:
        return f"{self._key_prefix}{session_id}/state.json"

    # -- Write -----------------------------------------------------------------

    async def write_state(self, session_id: str, state: SessionState) -> None:
        key = self._object_key(session_id)
        data = state.model_dump_json(indent=2)
        await to_thread.run_sync(
            partial(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data.encode("utf-8"),
                ContentType="application/json",
            )
        )

    # -- Read ------------------------------------------------------------------

    async def read_state(self, session_id: str) -> SessionState:
        key = self._object_key(session_id)
        body = await to_thread.run_sync(partial(self._get_object_body, key))
        return SessionState.model_validate_json(body)

    def _get_object_body(self, key: str) -> str:
        """Get object and read body in the same thread.

        Reading the streaming body must happen in the same thread as
        get_object to avoid issues with chunked transfer encoding.
        """
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
        except self._client.exceptions.NoSuchKey:
            msg = f"Session state not found: {key}"
            raise FileNotFoundError(msg) from None
        return resp["Body"].read().decode("utf-8")

    # -- Utilities -------------------------------------------------------------

    async def exists(self, session_id: str) -> bool:
        key = self._object_key(session_id)
        try:
            await to_thread.run_sync(partial(self._client.head_object, Bucket=self._bucket, Key=key))
        except self._client.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise
        else:
            return True

    async def delete(self, session_id: str) -> None:
        key = self._object_key(session_id)
        # S3 delete is idempotent -- no error if key doesn't exist.
        await to_thread.run_sync(partial(self._client.delete_object, Bucket=self._bucket, Key=key))
