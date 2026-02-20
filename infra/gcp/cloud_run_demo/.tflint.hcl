# tflint configuration for the demo Cloud Run + Cloud Scheduler stack.
#
# Notes:
# - `make tf-lint` runs tflint in a Docker container.
# - The Google ruleset is downloaded by `tflint --init`.

config {
  # Lint both root and module calls.
  call_module_type = "all"
}

plugin "google" {
  enabled = true
  version = "0.38.0"
  source  = "github.com/terraform-linters/tflint-ruleset-google"
}

# Terraform core rules
rule "terraform_unused_declarations" {
  enabled = true
}

rule "terraform_deprecated_interpolation" {
  enabled = true
}

rule "terraform_required_version" {
  enabled = true
}

rule "terraform_required_providers" {
  enabled = true
}
