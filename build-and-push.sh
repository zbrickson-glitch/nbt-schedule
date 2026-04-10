#!/bin/bash
set -e

# Build on kubernetes0 (x86) using k3s containerd via nerdctl.
# No local Docker Desktop needed.
#
# Usage: ./build-and-push.sh [node1 node2 ...]
# Defaults to deploying to: apprentice5 (primary worker for nbt pods)

NODES="${@:-apprentice5}"
IMAGE="docker.io/library/nbt-schedule-service:latest"
TAR="/tmp/nbt-schedule-service.tar"

echo "==> Syncing source to kubernetes0..."
rsync -a --exclude='venv/' --exclude='__pycache__/' --exclude='*.pyc' \
  "$(dirname "$0")/" kubernetes0:/tmp/nbt-build/

echo "==> Building image on kubernetes0 (linux/amd64)..."
ssh kubernetes0 "cd /tmp/nbt-build && sudo nerdctl \
  --address /run/k3s/containerd/containerd.sock \
  --namespace k8s.io \
  build -t nbt-schedule-service:latest . 2>&1"

echo "==> Exporting image to tar on kubernetes0..."
ssh kubernetes0 "sudo ctr -a /run/k3s/containerd/containerd.sock -n k8s.io \
  images export $TAR $IMAGE"

for NODE in $NODES; do
  echo "==> Distributing to $NODE..."
  ssh kubernetes0 "rsync -a $TAR root@${NODE}:/tmp/"
  ssh root@"${NODE}" "ctr -a /run/k3s/containerd/containerd.sock -n k8s.io \
    images import $TAR && echo '  imported on ${NODE}'"
done

echo "==> Done! Run: kubectl rollout restart deployment/nbt-schedule-service -n nbt"
