"""Bazel rules for running the conveyor-belt QA pipeline.

cb run requires git history and system tools (poetry, linters), so it
cannot run inside Bazel's sandbox. Two targets are provided:

- cb_qa_run:  sh_binary for `bazel run` (interactive, gets BUILD_WORKSPACE_DIRECTORY)
- cb_qa_test: sh_test with local=True for `bazel test` (CI-friendly exit code)
"""

def cb_qa_run(name, repo = ".", diff_ref = "HEAD~1", stations = [], **kwargs):
    """sh_binary for `bazel run //:<name>` — interactive use.

    Usage:
        load("//ci_adapters/bazel:defs.bzl", "cb_qa_run")
        cb_qa_run(name = "qa", stations = ["idiomatic"])
        # then: bazel run //:qa
    """
    native.sh_binary(
        name = name,
        srcs = ["//ci_adapters/bazel:run_cb.sh"],
        data = ["//:pyproject.toml", "//:poetry.lock"],
        env = {
            "CB_DIFF_REF": diff_ref,
            "CB_REPO": repo,
            "CB_STATIONS": " ".join(stations),
        },
        **kwargs
    )

def cb_qa_test(name, repo = ".", diff_ref = "HEAD~1", stations = [], **kwargs):
    """sh_test with local=True for `bazel test //:<name>` — CI use.

    Usage:
        load("//ci_adapters/bazel:defs.bzl", "cb_qa_test")
        cb_qa_test(name = "qa_check", stations = ["idiomatic"])
        # then: bazel test //:qa_check --test_env=PATH=$PATH --test_env=HOME=$HOME

    Note: requires --test_env=PATH=$PATH --test_env=HOME=$HOME because cb run
    needs system tools (poetry, git, ruff) that aren't in Bazel's default env.
    """
    native.sh_test(
        name = name,
        srcs = ["//ci_adapters/bazel:run_cb.sh"],
        data = ["//:pyproject.toml", "//:poetry.lock"],
        env = {
            "CB_DIFF_REF": diff_ref,
            "CB_REPO": repo,
            "CB_STATIONS": " ".join(stations),
        },
        local = True,
        size = "large",
        timeout = "long",
        **kwargs
    )
