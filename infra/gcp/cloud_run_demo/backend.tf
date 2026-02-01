// Terraform remote state (GCS)
// Backend config is passed by the repo root Makefile.
terraform {
  backend "gcs" {}
}
