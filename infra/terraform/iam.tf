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

# ── Task role ───────────────────────────────────────────────────────────────
# Assumed by the running container. Attach additional policies here as the
# app grows (e.g. S3 access for artefacts, Secrets Manager for API keys).
resource "aws_iam_role" "task" {
  name               = "${local.prefix}-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}
