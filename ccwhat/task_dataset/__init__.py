"""Task Dataset v1 core APIs."""

from .builder import (
    DatasetBuildError,
    build_dataset_bundle,
    build_dataset_bundle_from_segments,
)
from .change_evidence import extract_change_evidence
from .models import (
    CHANGE_CONFIDENCES,
    CHANGE_KINDS,
    DATASET_SCHEMA_VERSION,
    DIFFS_DIR,
    DatasetBundle,
    DatasetChangeEvidence,
    DatasetItemRow,
    DatasetManifest,
    DatasetPatchEvidence,
    DatasetScoreRow,
    DatasetTrace,
    TaskDiffEvidence,
    PATCH_CONFIDENCES,
    PATCH_FORMATS,
    ValidationIssue,
    ValidationResult,
)
from .registry import (
    DatasetRegistryError,
    build_dataset_tar_gz,
    default_dataset_registry_root,
    save_task_dataset_from_request,
)
from .validator import validate_dataset, validate_dataset_path

__all__ = [
    "DATASET_SCHEMA_VERSION",
    "DIFFS_DIR",
    "CHANGE_CONFIDENCES",
    "CHANGE_KINDS",
    "DatasetBuildError",
    "DatasetBundle",
    "DatasetChangeEvidence",
    "DatasetItemRow",
    "DatasetManifest",
    "DatasetPatchEvidence",
    "DatasetRegistryError",
    "DatasetScoreRow",
    "DatasetTrace",
    "TaskDiffEvidence",
    "PATCH_CONFIDENCES",
    "PATCH_FORMATS",
    "ValidationIssue",
    "ValidationResult",
    "build_dataset_bundle",
    "build_dataset_bundle_from_segments",
    "build_dataset_tar_gz",
    "default_dataset_registry_root",
    "extract_change_evidence",
    "save_task_dataset_from_request",
    "validate_dataset",
    "validate_dataset_path",
]
