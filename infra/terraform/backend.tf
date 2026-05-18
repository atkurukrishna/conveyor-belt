# Local state — works out of the box, no setup needed.
# To switch to S3 remote state (recommended for teams), copy
# backend.tf.example to backend.tf and fill in your bucket/table names,
# then run: terraform init -migrate-state
terraform {
  backend "local" {}
}
