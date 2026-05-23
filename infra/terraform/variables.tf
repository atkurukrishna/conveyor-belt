variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "ap-south-1"
}

variable "app_name" {
  description = "Application name — used as a prefix for all resources."
  type        = string
  default     = "conveyor-belt"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)."
  type        = string
  default     = "dev"
}

variable "container_image" {
  description = "Full ECR image URI (repo:tag). Leave empty to use the ECR repo URL as a placeholder."
  type        = string
  default     = ""
}

variable "container_port" {
  description = "Port the FastAPI server listens on inside the container."
  type        = number
  default     = 8000
}

variable "cpu" {
  description = "Fargate task CPU units (256 | 512 | 1024 | 2048 | 4096)."
  type        = number
  default     = 512
}

variable "memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 1024
}

variable "desired_count" {
  description = "Number of ECS task replicas."
  type        = number
  default     = 1
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to spread across (2 or 3)."
  type        = number
  default     = 2
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
  default     = 30
}

variable "certificate_arn" {
  description = "ACM certificate ARN for HTTPS. Leave empty to keep the HTTP-only listener (dev mode)."
  type        = string
  default     = ""
}

variable "app_secrets_arn" {
  description = "ARN of a Secrets Manager secret (JSON) containing ANTHROPIC_API_KEY, GOOGLE_API_KEY, SNYK_TOKEN, LINEAR_API_KEY. Leave empty to skip."
  type        = string
  default     = ""
}
