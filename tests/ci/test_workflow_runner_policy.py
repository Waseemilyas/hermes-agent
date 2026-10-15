"""Prevent hosted runner drift from queuing jobs on unavailable runner labels."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
UPSTREAM = "NousResearch/hermes-agent"


def _workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _repo_runner(large_runner, fork_runner):
    return (
        "${{ github.repository == 'NousResearch/hermes-agent' "
        f"&& '{large_runner}' || '{fork_runner}' "
        "}}"
    )


def test_ubuntu_runner_defaults_are_pinned():
    """The fork must not queue or time out on moving or private runner labels."""
    workflows = [*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")]
    assert workflows, "workflow files must exist for CI to run"

    for path in workflows:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_name, job in (workflow.get("jobs") or {}).items():
            selectors = [job.get("runs-on")]
            matrix = (job.get("strategy") or {}).get("matrix") or {}
            selectors.extend(
                entry.get("runner")
                for entry in matrix.get("include", [])
                if isinstance(entry, dict)
            )
            assert "ubuntu-latest" not in selectors, f"{path.name}:{job_name}"

    install_e2e = _workflow("install-e2e-run.yml")
    call = install_e2e.get("on")
    if call is None:  # PyYAML's YAML 1.1 loader treats the key `on` as True.
        call = install_e2e.get(True)
    assert call["workflow_call"]["inputs"]["runner"]["default"] == "ubuntu-24.04"


def test_large_jobs_keep_upstream_capacity_and_use_supported_fork_runners():
    """The fork gets hosted runners while upstream retains its measured capacity."""
    expected = {
        ("tests.yml", "test"): ("ubuntu-latest-96-core", "ubuntu-24.04"),
        ("js-tests.yml", "check"): ("ubuntu-latest-32-core", "ubuntu-24.04"),
        ("nix.yml", "flake-check"): ("ubuntu-latest-32-core", "ubuntu-24.04"),
        ("rust-tests.yml", "bootstrap-installer"): (
            "ubuntu-latest-32-core",
            "ubuntu-24.04",
        ),
        ("e2e-desktop.yml", "e2e"): ("ubuntu-latest-32-core", "ubuntu-24.04"),
    }
    for (workflow_name, job_name), (large_runner, fork_runner) in expected.items():
        assert _workflow(workflow_name)["jobs"][job_name]["runs-on"] == _repo_runner(
            large_runner, fork_runner
        )

    windows = (
        _workflow("tests-os.yml")["jobs"]["os-tests"]["strategy"]["matrix"]["include"]
    )
    windows_runner = next(
        entry["runner"] for entry in windows if entry["name"] == "Windows-only tests"
    )
    assert windows_runner == _repo_runner("windows-latest-32-core", "windows-latest")

    docker = _workflow("docker.yml")["jobs"]
    amd64 = _repo_runner("ubuntu-latest-32-core", "ubuntu-24.04")
    arm64 = _repo_runner("ubuntu-latest-32-arm-core", "ubuntu-24.04-arm")
    for job_name in ("build", "publish"):
        job = docker[job_name]
        assert f"github.repository == '{UPSTREAM}'" in job["if"]
        runners = {
            entry["arch"]: entry["runner"]
            for entry in job["strategy"]["matrix"]["include"]
        }
        assert runners["amd64"] == amd64
        assert runners["arm64"] == arm64
