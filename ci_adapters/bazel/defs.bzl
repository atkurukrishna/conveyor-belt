"""Bazel rule for running the conveyor-belt QA pipeline."""

def cb_qa_test(name, repo = ".", diff_ref = "HEAD~1", stations = [], **kwargs):
    """Wraps `cb run` as a Bazel sh_test target.

    Usage in BUILD:
        load("//ci_adapters/bazel:defs.bzl", "cb_qa_test")

        cb_qa_test(
            name = "qa_check",
            diff_ref = "HEAD~1",
            stations = ["idiomatic", "unit_coverage"],
        )

    Args:
        name: Target name.
        repo: Repository root path (default: ".").
        diff_ref: Git ref for diff (default: "HEAD~1").
        stations: List of station names to run. Empty = all enabled.
        **kwargs: Passed through to sh_test.
    """
    station_args = " ".join(["--station " + s for s in stations])

    native.sh_test(
        name = name,
        srcs = ["//ci_adapters/bazel:run_cb.sh"],
        args = [
            "--diff", diff_ref,
            "--repo", repo,
        ] + (["--station " + s for s in stations] if stations else []),
        data = [
            "//:pyproject.toml",
            "//:poetry.lock",
        ],
        env = {
            "CB_DIFF_REF": diff_ref,
            "CB_REPO": repo,
            "CB_STATIONS": " ".join(stations),
        },
        size = "large",
        timeout = "long",
        **kwargs
    )
