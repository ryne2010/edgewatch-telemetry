# module: network

Creates a custom-mode VPC and one or more subnets, with an optional **Serverless VPC Access connector**
for Cloud Run connectivity to private resources.

## Notes
- This module does **not** create Cloud NAT by default (to keep cost low).
- If you need private egress via NAT, add Cloud Router + NAT separately.
