load("//ci_adapters/bazel:defs.bzl", "cb_qa_run", "cb_qa_test")

# Interactive: bazel run //:qa
cb_qa_run(
    name = "qa",
    diff_ref = "HEAD~1",
    stations = ["idiomatic"],
)

# CI: bazel test //:qa_check --test_env=PATH=$PATH --test_env=HOME=$HOME
cb_qa_test(
    name = "qa_check",
    diff_ref = "HEAD~1",
    stations = ["idiomatic"],
)
