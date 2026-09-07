"""Configuration-selected storage factories."""

import os

from aidlc.storage.files import ArtifactStore as FileArtifactStore
from aidlc.storage.files import FileRunRepository, Tracer as FileTracer


def get_artifact_store(run_id: str):
    if os.getenv("AIDLC_DATABASE_URL"):
        from aidlc.storage.postgres import PostgresArtifactStore

        return PostgresArtifactStore(run_id)
    return FileArtifactStore(run_id)


def get_tracer(run_id: str):
    if os.getenv("AIDLC_DATABASE_URL"):
        from aidlc.storage.postgres import PostgresTracer

        return PostgresTracer(run_id)
    return FileTracer(run_id)


def get_run_repository():
    if os.getenv("AIDLC_DATABASE_URL"):
        from aidlc.storage.postgres import PostgresRunRepository

        return PostgresRunRepository()
    return FileRunRepository()
