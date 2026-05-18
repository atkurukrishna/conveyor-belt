data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  prefix = "${var.app_name}-${var.environment}"

  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  common_tags = {
    Project     = var.app_name
    Environment = var.environment
    ManagedBy   = "Terraform"
  }
}
