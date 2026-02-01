# IAM starter pack (Google Groups)

This repo includes an **optional** Terraform IAM layer (`infra/gcp/cloud_run_demo/iam_bindings.tf`) that models a small production team using **Google Groups** (Workspace / Cloud Identity):

- **clients-observers**: view-only access (dashboards + service-scoped logs)
- **engineers-min**: deploy + troubleshoot with limited privileges
- **engineers**: build/operate with broader privileges
- **auditors**: read-only audit access
- **platform-admins**: platform ownership (use carefully)

Why this is staff-level relevant:
- You can explain **least privilege**, **separation of duties**, and **auditability**.
- Access changes become **reviewable code changes** (Terraform plan + PR).
- External stakeholders can observe without gaining broad project visibility.

---

## Two-tier IAM model (recommended)

**Best practice:** keep **project-level IAM** in one central "platform baseline" repo (Repo 3), and keep application repos focused on **app-scoped resources**.

This repo supports both modes:

1) **Recommended (team / multi-repo):**  
   - Project IAM is managed centrally in the platform repo.
   - This repo only grants *app-scoped* IAM (e.g., Cloud Run invoker + client log view access).

2) **Standalone demo mode:**  
   - Set `enable_project_iam = true` to let this repo manage project-level IAM too.

---

## Required inputs

These Terraform variables drive group identities:

- `workspace_domain` (your Google Workspace domain, e.g., `example.com`)
- `group_prefix` (defaults to `edgewatch` for this repo)

When `workspace_domain` is empty, the repo creates **no** group bindings.

---

## Recommended group naming scheme

The repo expects these groups to exist:

- `${group_prefix}-clients-observers@${workspace_domain}`
- `${group_prefix}-engineers-min@${workspace_domain}`
- `${group_prefix}-engineers@${workspace_domain}`
- `${group_prefix}-auditors@${workspace_domain}`
- `${group_prefix}-platform-admins@${workspace_domain}`

---

## Log Views: give clients service-scoped log access (without project-wide logging)

Clients often need access to logs **for one service only**. Granting `roles/logging.viewer` at the project level is too broad.

This repo uses a strong pattern:

1) A **Logs Router sink** routes only this Cloud Run service’s logs into a **dedicated log bucket**.
2) A **log view** is created over that bucket.
3) The `clients-observers` group gets `roles/logging.viewAccessor` on the project **with an IAM Condition** pinned to that specific view.

Files:
- `infra/gcp/cloud_run_demo/log_views.tf` (bucket + sink + view)
- `infra/gcp/cloud_run_demo/iam_bindings.tf` (IAM Condition for `viewAccessor`)

---

## Role mapping (high level)

This is the intended permission shape:

### clients-observers
- Monitoring dashboards: **viewer**
- Logs: **viewAccessor (conditioned to a single log view)**

### engineers-min
- Cloud Run: **developer**
- Artifact Registry: **reader**
- Monitoring: **viewer**

### engineers
- Cloud Run: **admin**
- Artifact Registry: **writer**
- Monitoring/Logging: **viewer**
- Secret access: **secretAccessor** (if used)

### auditors
- Monitoring/Logging: **viewer**

### platform-admins
- IAM admin + service account admin + service usage admin
- Run admin, AR admin, Secret Manager admin, Monitoring/Logging admin

> **Note:** platform-admins is intentionally powerful and should be small, MFA-enforced, and audited.

---

## How to enable in Terraform

Set (in your Terraform variable source: tfvars, CI vars, etc.):

```hcl
workspace_domain  = "example.com"
group_prefix      = "edgewatch"
enable_project_iam = false # recommended when using the platform baseline repo
```

If you want this repo to be fully standalone:

```hcl
enable_project_iam = true
```
