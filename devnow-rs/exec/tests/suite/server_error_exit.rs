#![cfg(not(target_os = "windows"))]
#![allow(clippy::expect_used, clippy::unwrap_used)]

use core_test_support::responses;
use core_test_support::test_codex_exec::test_codex_exec;
use predicates::prelude::*;

/// Verify that when the server reports an error, `codex-exec` exits with a
/// non-zero status code so automation can detect failures.
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn exits_non_zero_when_server_reports_error() -> anyhow::Result<()> {
    for ephemeral in [false, true] {
        let test = test_codex_exec();
        let server = responses::start_mock_server().await;
        let body = responses::sse(vec![serde_json::json!({
            "type": "response.failed",
            "response": {
                "id": "resp_err_1",
                "error": {"code": "rate_limit_exceeded", "message": "synthetic server error"}
            }
        })]);
        responses::mount_sse_once(&server, body).await;

        let mut command = test.cmd_with_server(&server);
        command
            .arg("--skip-git-repo-check")
            .arg("tell me something")
            .arg("--experimental-json");
        if ephemeral {
            command.arg("--ephemeral");
        }
        command
            .assert()
            .code(1)
            .stdout(predicate::str::contains("\"type\":\"turn.failed\""));
    }

    Ok(())
}
