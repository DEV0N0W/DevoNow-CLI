use anyhow::Result;
use predicates::prelude::*;

fn devnow_command() -> Result<assert_cmd::Command> {
    Ok(assert_cmd::Command::new(codex_utils_cargo_bin::cargo_bin(
        "codex",
    )?))
}

#[test]
fn help_uses_public_devnow_branding() -> Result<()> {
    devnow_command()?
        .arg("--help")
        .assert()
        .success()
        .stdout(predicate::str::contains("DevoNow CLI"))
        .stdout(predicate::str::contains("Usage: devnow"))
        .stdout(predicate::str::contains("Run DevoNow non-interactively"))
        .stdout(predicate::str::contains("Codex desktop app").not())
        .stdout(predicate::str::contains("Codex Cloud").not())
        .stdout(predicate::str::contains("Usage: codex").not());

    Ok(())
}

#[test]
fn version_uses_public_devnow_command_name() -> Result<()> {
    devnow_command()?
        .arg("--version")
        .assert()
        .success()
        .stdout(predicate::str::starts_with("devnow "));

    Ok(())
}

#[test]
fn shell_completion_registers_public_devnow_command() -> Result<()> {
    devnow_command()?
        .args(["completion", "bash"])
        .assert()
        .success()
        .stdout(predicate::str::contains("_devnow()"))
        .stdout(predicate::str::contains("complete -F _devnow"))
        .stdout(predicate::str::contains("_codex()").not());

    Ok(())
}
