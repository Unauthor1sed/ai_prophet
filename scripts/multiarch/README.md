# 双架构 images.tar 构建脚本

三步产出同时支持 amd64 + arm64 的离线镜像包：

```bash
# 1.（仅当 daemon 拉不动 Docker Hub 时）经镜像站拉取双架构基础镜像并导入
python3 scripts/multiarch/pull_base_image.py
docker load -i <脚本输出的 base-image.tar>
# amd64 变体单独打标签供交叉构建使用（见脚本注释）

# 2. 分别构建两个架构（Apple Silicon 上 amd64 走 Rosetta 模拟）
docker build -t ai-prophet:latest .
docker build --platform linux/amd64 --build-arg BASE_IMAGE=python-amd64:3.11-slim -t ai-prophet:amd64 .

# 3. 合并为一个多架构 tar
python3 scripts/multiarch/merge_images.py ai-prophet:latest ai-prophet:amd64 images.tar
```

- `pull_base_image.py`：绕过 Docker daemon（代理失效场景），用宿主机网络直接调
  Registry v2 API 从国内镜像站下载 python:3.11-slim 的 amd64+arm64 层文件，
  组装为 OCI layout tar。含断点续传与多镜像站轮询。
- `merge_images.py`：把两个单架构镜像合并成带**多架构索引**的单一 tar，
  `docker load` 时按目标机器 CPU 自动选择架构。文件头部注释解释了索引结构
  与 Docker 内部的架构匹配逻辑。

> 网络正常的机器不需要这些：`docker buildx build --platform linux/amd64,linux/arm64` 一条命令等价。
> 这套脚本解决的是"构建机 Docker daemon 代理失效 + 需要离线交付"的组合场景。
