"""M5.1 explicit review and promotion of quarantined memory candidates."""

from __future__ import annotations

import pytest

from agentguard.schemas import MemoryCandidateStatus
from agentguard.tools import (
    SimulatedEnvironment,
    memory_candidate_hash,
    promote_memory_candidate,
    quarantine_memory,
    review_memory_candidate,
)


def environment_with_candidate() -> SimulatedEnvironment:
    environment = SimulatedEnvironment(emails=[], files={})
    quarantine_memory(
        environment,
        {"content": "reviewed fact", "source": "claim", "namespace": "candidate"},
        provenance_source_ids=("untrusted-email-1",),
    )
    return environment


def test_approved_unchanged_candidate_can_be_promoted_once() -> None:
    environment = environment_with_candidate()
    candidate = environment.memory_candidates[0]
    expected_hash = memory_candidate_hash(candidate)

    review_memory_candidate(
        environment,
        candidate.id,
        expected_content_hash=expected_hash,
        approve=True,
    )
    entry = promote_memory_candidate(
        environment,
        candidate.id,
        expected_content_hash=expected_hash,
        target_namespace="reviewed",
    )

    assert candidate.status is MemoryCandidateStatus.PROMOTED
    assert entry.content == "reviewed fact"
    assert entry.namespace == "reviewed"
    assert entry.source == f"candidate:{candidate.id}"
    with pytest.raises(ValueError, match="not approved"):
        promote_memory_candidate(
            environment,
            candidate.id,
            expected_content_hash=expected_hash,
            target_namespace="reviewed",
        )


def test_candidate_hash_mismatch_prevents_review() -> None:
    environment = environment_with_candidate()
    candidate = environment.memory_candidates[0]

    with pytest.raises(ValueError, match="hash does not match"):
        review_memory_candidate(
            environment,
            candidate.id,
            expected_content_hash="0" * 64,
            approve=True,
        )

    assert candidate.status is MemoryCandidateStatus.PENDING


def test_rejected_candidate_cannot_be_promoted() -> None:
    environment = environment_with_candidate()
    candidate = environment.memory_candidates[0]
    expected_hash = memory_candidate_hash(candidate)
    review_memory_candidate(
        environment,
        candidate.id,
        expected_content_hash=expected_hash,
        approve=False,
    )

    assert candidate.status is MemoryCandidateStatus.REJECTED
    with pytest.raises(ValueError, match="not approved"):
        promote_memory_candidate(
            environment,
            candidate.id,
            expected_content_hash=expected_hash,
            target_namespace="reviewed",
        )

