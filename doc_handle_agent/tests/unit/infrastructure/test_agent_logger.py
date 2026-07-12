from app.utils.agent_logger import AgentLogger


def test_agent_logger_uses_unique_file_for_concurrent_sessions(tmp_path):
    first = AgentLogger(
        repo_id="repo-1",
        task_name="batch",
        session_id="11111111-1111-1111-1111-111111111111",
        log_dir=tmp_path,
    )
    second = AgentLogger(
        repo_id="repo-1",
        task_name="batch",
        session_id="22222222-2222-2222-2222-222222222222",
        log_dir=tmp_path,
    )

    try:
        assert first.log_file != second.log_file
        assert "11111111" in first.log_file.name
        assert "22222222" in second.log_file.name
    finally:
        for agent_logger in (first, second):
            for handler in list(agent_logger.logger.handlers):
                handler.close()
                agent_logger.logger.removeHandler(handler)
