resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.prefix}"
  retention_in_days = var.log_retention_days

  tags = { Name = "${local.prefix}-logs" }
}
