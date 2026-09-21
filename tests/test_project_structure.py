import agentguard


def test_package_import() -> None:
    assert agentguard.__version__ == "0.1.0"
