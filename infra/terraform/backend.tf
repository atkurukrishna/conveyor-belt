# Remote state — create the bucket + table once before `terraform init`:
#
#   aws s3api create-bucket \
#     --bucket <tfstate-bucket> --region us-east-1
#
#   aws dynamodb create-table \
#     --table-name <lock-table> \
#     --attribute-definitions AttributeName=LockID,AttributeType=S \
#     --key-schema AttributeName=LockID,KeyType=HASH \
#     --billing-mode PAY_PER_REQUEST --region us-east-1
#
terraform {
  backend "s3" {
    bucket         = "REPLACE_WITH_YOUR_TFSTATE_BUCKET"
    key            = "conveyor-belt/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "REPLACE_WITH_YOUR_LOCK_TABLE"
    encrypt        = true
  }
}
