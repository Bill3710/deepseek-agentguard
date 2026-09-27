"""Offline tests for the M3 online report evaluator."""

from scripts.run_m3_usability import check_expected_facts, check_expected_state


def test_expected_facts_accept_chinese_grounded_status() -> None:
    assert check_expected_facts(
        {"project": "Project Alpha", "status": "on schedule"},
        "Project Alpha 当前按计划进行。",
    )


def test_expected_facts_reject_missing_project() -> None:
    assert not check_expected_facts(
        {"project": "Project Alpha", "status": "on schedule"},
        "项目目前按计划进行。",
    )


def test_expected_memory_state_is_checked_without_outbox_requirement() -> None:
    expected = {
        "memory_count": 1,
        "memory_content": "Project Alpha status checked",
        "memory_source": "manual-test",
    }
    actual = {
        "memory_count": 1,
        "memory": [
            {
                "id": "memory-001",
                "content": "Project Alpha status checked",
                "source": "manual-test",
            }
        ],
        "outbox_count": 0,
        "outbox": [],
    }

    assert check_expected_state(expected, actual)


def test_expected_outbox_state_is_checked_without_memory_requirement() -> None:
    expected = {
        "outbox_count": 1,
        "recipient": "reviewer@example.test",
        "subject": "AgentGuard M3 Test",
        "body": "Synthetic delivery check",
    }
    actual = {
        "memory_count": 0,
        "memory": [],
        "outbox_count": 1,
        "outbox": [
            {
                "id": "outbox-001",
                "to": "reviewer@example.test",
                "subject": "AgentGuard M3 Test",
                "body": "Synthetic delivery check",
            }
        ],
    }

    assert check_expected_state(expected, actual)
