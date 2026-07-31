#!/usr/bin/env python3
"""把分别构建的 amd64/arm64 两个镜像合并为一个多架构 images.tar

原理：OCI 镜像格式支持"索引套索引"。生成的 tar 结构为：

    index.json  (顶层索引：两个标签 → 同一个内层多架构索引)
      └─ 内层索引 blob:
           ├─ {platform: linux/amd64} → amd64 镜像清单 → 各层文件
           └─ {platform: linux/arm64} → arm64 镜像清单 → 各层文件
    blobs/sha256/*  (两个架构的全部层，内容寻址自动去重)

docker load 读到内层索引时，按本机 CPU 架构挑选匹配的 platform 条目导入
（"选哪个架构"的判断发生在 Docker/containerd 内部，匹配逻辑等价于：
  if manifest.platform.architecture == 本机架构: 导入这一份）。

用法（先分别构建好两个架构的镜像）：
    docker build -t ai-prophet:latest .
    docker build --platform linux/amd64 --build-arg BASE_IMAGE=python-amd64:3.11-slim -t ai-prophet:amd64 .
    python3 scripts/multiarch/merge_images.py ai-prophet:latest ai-prophet:amd64 images.tar
"""
import json
import os
import sys
import shutil
import hashlib
import tarfile
import tempfile
import subprocess

TAGS = ["ai-prophet:latest", "ai_prophet-api:latest"]  # 合并包里挂的标签


def docker_save_extract(image: str, dest: str) -> dict:
    """docker save 并解包，返回其 index.json 中的镜像清单描述符"""
    tar_path = os.path.join(dest, "img.tar")
    subprocess.run(["docker", "save", image, "-o", tar_path], check=True)
    with tarfile.open(tar_path) as t:
        t.extractall(dest)
    os.remove(tar_path)
    idx = json.load(open(os.path.join(dest, "index.json")))
    m = idx["manifests"][0]
    return {"mediaType": m["mediaType"], "digest": m["digest"], "size": m["size"]}


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    arm_image, amd_image, out_tar = sys.argv[1], sys.argv[2], sys.argv[3]

    work = tempfile.mkdtemp(prefix="multiarch_")
    arm_dir, amd_dir = os.path.join(work, "arm"), os.path.join(work, "amd")
    merged = os.path.join(work, "merged")
    os.makedirs(arm_dir)
    os.makedirs(amd_dir)
    os.makedirs(os.path.join(merged, "blobs", "sha256"))

    print(f"导出 {arm_image} (arm64) ...")
    arm_desc = docker_save_extract(arm_image, arm_dir)
    print(f"导出 {amd_image} (amd64) ...")
    amd_desc = docker_save_extract(amd_image, amd_dir)

    # 合并两边的层文件（sha256 内容寻址，同名即同内容，直接并集）
    for d in (arm_dir, amd_dir):
        src = os.path.join(d, "blobs", "sha256")
        for f in os.listdir(src):
            dst = os.path.join(merged, "blobs", "sha256", f)
            if not os.path.exists(dst):
                shutil.copy2(os.path.join(src, f), dst)

    # 内层多架构索引：给每个清单标注 platform
    arm_desc["platform"] = {"os": "linux", "architecture": "arm64"}
    amd_desc["platform"] = {"os": "linux", "architecture": "amd64"}
    inner = {"schemaVersion": 2,
             "mediaType": "application/vnd.oci.image.index.v1+json",
             "manifests": [amd_desc, arm_desc]}
    raw = json.dumps(inner).encode()
    inner_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    with open(os.path.join(merged, "blobs", "sha256", inner_digest.split(":")[1]), "wb") as f:
        f.write(raw)

    # 顶层索引：每个交付标签都指向同一个内层索引
    def ref(tag):
        return {"mediaType": "application/vnd.oci.image.index.v1+json",
                "digest": inner_digest, "size": len(raw),
                "annotations": {"io.containerd.image.name": f"docker.io/library/{tag}",
                                "org.opencontainers.image.ref.name": tag.split(":")[-1]}}

    json.dump({"schemaVersion": 2,
               "mediaType": "application/vnd.oci.image.index.v1+json",
               "manifests": [ref(t) for t in TAGS]},
              open(os.path.join(merged, "index.json"), "w"))
    json.dump({"imageLayoutVersion": "1.0.0"}, open(os.path.join(merged, "oci-layout"), "w"))

    with tarfile.open(out_tar, "w") as t:
        for name in ("oci-layout", "index.json", "blobs"):
            t.add(os.path.join(merged, name), arcname=name)
    shutil.rmtree(work)
    print(f"完成: {out_tar} ({os.path.getsize(out_tar) // 1024 // 1024}MB, 含 amd64+arm64)")
    print("验证: docker load -i", out_tar, "&& docker image ls ai-prophet --tree")


if __name__ == "__main__":
    main()
