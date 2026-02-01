# module: artifact_registry

Creates a Docker Artifact Registry repository for Cloud Run (or other) workloads.

Use the `docker_repository` output to tag/push images, e.g.:

```bash
docker tag myapp:latest $(terraform output -raw docker_repository)/myapp:latest
docker push $(terraform output -raw docker_repository)/myapp:latest
```
