output "app_url" {
  description = "Public URL of the Conveyor Belt dashboard."
  value       = "http://${aws_lb.main.dns_name}"
}

output "ecr_repository_url" {
  description = "ECR repository URL — use this in `docker push` and CI."
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.app.name
}

output "log_group_name" {
  description = "CloudWatch log group for ECS task output."
  value       = aws_cloudwatch_log_group.app.name
}

output "vpc_id" {
  description = "VPC ID."
  value       = aws_vpc.main.id
}
