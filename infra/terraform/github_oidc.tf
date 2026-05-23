variable "github_repo" {
  description = "GitHub repository in owner/repo format (e.g. acme/conveyor-belt). Used to scope the OIDC trust policy."
  type        = string
  default     = "atkurukrishna/conveyor-belt"
}

# ── GitHub Actions OIDC provider ─────────────────────────────────────────────
# One provider per AWS account — use data source if it already exists.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

# Use the existing provider if it exists, otherwise create it.
# Note: Terraform doesn't support conditional resources directly.
# If you get an error, you may need to import the existing provider into your state:
# terraform import aws_iam_openid_connect_provider.github <arn>
resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = ["sts.amazonaws.com"]

  # GitHub's OIDC thumbprint (stable — changes only when GitHub rotates their CA).
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

# ── Deploy role ───────────────────────────────────────────────────────────────
# Assumed by GitHub Actions on pushes to master only.
data "aws_iam_policy_document" "github_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Scoped to master branch of this repo only — no other branch or fork can
    # assume this role.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/master"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${local.prefix}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_assume.json
}

# ── Deploy role permissions ───────────────────────────────────────────────────
data "aws_iam_policy_document" "github_deploy" {
  # ECR — push images
  statement {
    effect = "Allow"
    actions = [
      "ecr:GetAuthorizationToken",
    ]
    resources = ["*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "ecr:BatchGetImage",
      "ecr:BatchCheckLayerAvailability",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.app.arn]
  }

  # ECS — read task definition, register new revision, update service
  statement {
    effect = "Allow"
    actions = [
      "ecs:DescribeTaskDefinition",
      "ecs:RegisterTaskDefinition",
    ]
    resources = ["*"]
  }

  statement {
    effect = "Allow"
    actions = [
      "ecs:DescribeServices",
      "ecs:UpdateService",
    ]
    # aws_ecs_service.id IS the service ARN — the provider exports no separate .arn attribute.
    resources = [aws_ecs_service.app.id]
  }

  # IAM — allow passing the task execution and task roles to ECS
  statement {
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [
      aws_iam_role.execution.arn,
      aws_iam_role.task.arn,
    ]
  }
}

resource "aws_iam_policy" "github_deploy" {
  name   = "${local.prefix}-github-deploy"
  policy = data.aws_iam_policy_document.github_deploy.json
}

resource "aws_iam_role_policy_attachment" "github_deploy" {
  role       = aws_iam_role.github_deploy.name
  policy_arn = aws_iam_policy.github_deploy.arn
}

# ── Output ────────────────────────────────────────────────────────────────────
output "github_deploy_role_arn" {
  description = "Set as GitHub secret AWS_DEPLOY_ROLE_ARN in the repository settings."
  value       = aws_iam_role.github_deploy.arn
}
