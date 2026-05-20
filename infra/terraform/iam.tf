data "aws_iam_policy_document" "ecs_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ── Execution role ──────────────────────────────────────────────────────────
# Used by the ECS control plane to pull images from ECR and ship logs to
# CloudWatch. Attach the AWS-managed policy — it covers exactly these actions.
resource "aws_iam_role" "execution" {
  name               = "${local.prefix}-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ── Execution role — Secrets Manager access ─────────────────────────────────
# The execution role (not the task role) needs GetSecretValue so ECS can
# inject secrets before the container starts.
data "aws_iam_policy_document" "execution_secrets" {
  count = var.app_secrets_arn != "" ? 1 : 0

  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.app_secrets_arn]
  }
}

resource "aws_iam_policy" "execution_secrets" {
  count  = var.app_secrets_arn != "" ? 1 : 0
  name   = "${local.prefix}-execution-secrets"
  policy = data.aws_iam_policy_document.execution_secrets[0].json
}

resource "aws_iam_role_policy_attachment" "execution_secrets" {
  count      = var.app_secrets_arn != "" ? 1 : 0
  role       = aws_iam_role.execution.name
  policy_arn = aws_iam_policy.execution_secrets[0].arn
}

# ── Task role ───────────────────────────────────────────────────────────────
# Assumed by the running container. Attach additional policies here as the
# app grows (e.g. S3 access for artefacts).
resource "aws_iam_role" "task" {
  name               = "${local.prefix}-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
