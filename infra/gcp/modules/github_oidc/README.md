# module: github_oidc

Configures **GitHub Actions → GCP Workload Identity Federation** (OIDC), so CI can run Terraform without long-lived
service account keys.

## Usage
1) Create a CI service account (or reuse one)
2) Apply this module for your `OWNER/REPO`
3) Use the outputs in GitHub Actions

Example (GitHub Actions auth step):

```yaml
- id: auth
  uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ secrets.GCP_WIF_PROVIDER }}
    service_account: ${{ secrets.GCP_SA_EMAIL }}
```

> Tip: Store the provider name and service account email as GitHub repo secrets.
