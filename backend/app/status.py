"""Canonical status definitions for ViralClip AI jobs and clips.

All job and clip database statuses are normalized to lowercase.
Upper-case import progress states (QUEUED, UPLOADING, etc.) are kept in
job.settings["import_state"] for user-facing UI telemetry.
"""
from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "queued"
    INITIALIZING = "initializing"
    DOWNLOADING = "downloading"
    UPLOADING = "uploading"
    VALIDATING = "validating"
    EXTRACTING_METADATA = "extracting_metadata"
    ANALYZING = "analyzing"
    TRANSCRIBING = "transcribing"
    DETECTING = "detecting"
    READY = "ready"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ClipStatus(str, Enum):
    DETECTED = "detected"
    SELECTED = "selected"
    REJECTED = "rejected"
    EXPORTING = "exporting"
    EXPORTED = "exported"
    EXPORT_FAILED = "export_failed"


ACTIVE_JOB_STATUSES = {
    JobStatus.QUEUED.value,
    JobStatus.INITIALIZING.value,
    JobStatus.DOWNLOADING.value,
    JobStatus.UPLOADING.value,
    JobStatus.VALIDATING.value,
    JobStatus.EXTRACTING_METADATA.value,
    JobStatus.ANALYZING.value,
    JobStatus.TRANSCRIBING.value,
    JobStatus.DETECTING.value,
}

TERMINAL_JOB_STATUSES = {
    JobStatus.READY.value,
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
}


def normalize_status(val: str | None) -> str:
    if not val:
        return JobStatus.QUEUED.value
    return val.strip().lower()


def to_import_state(status: str) -> str:
    """Format status as uppercase import_state for UI compatibility."""
    return (status or "").strip().upper()
