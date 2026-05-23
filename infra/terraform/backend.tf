# S3 remote state with DynamoDB locking.
# Create the bucket + table once, then copy this file to backend.tf
# and run: terraform init -migrate-state
#
#   aws s3api create-bucket \
#     --bucket <tfstate-bucket> --region ap-south-1
#
#   aws dynamodb create-table \
#     --table-name <lock-table> \
#     --attribute-definitions AttributeName=LockID,AttributeType=S \
#     --key-schema AttributeName=LockID,KeyType=HASH \
#     --billing-mode PAY_PER_REQUEST --region ap-south-1
#
terraform {
  backend "s3" {
    bucket         = "proj-conveyor-belt-terraform-repo-637565374412-ap-south-1-an"
    key            = "conveyor-belt/terraform.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "conveyor-belt-tflock"
    encrypt        = true
  }
}
