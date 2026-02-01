# module: secret_manager

Creates Secret Manager **secret containers** only.

Why no secret versions?
- Secret values stored via Terraform end up in Terraform state. For safer workflows, add versions out-of-band:

```bash
echo -n "my-secret-value" | gcloud secrets versions add MY_SECRET --data-file=-
```
