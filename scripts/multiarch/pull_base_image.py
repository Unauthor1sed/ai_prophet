#!/usr/bin/env python3
"""经宿主机网络从镜像站拉取 python:3.11-slim 双架构镜像，组装 OCI layout tar 供 docker load"""
import json, os, sys, hashlib, tarfile, urllib.request, urllib.parse, re, shutil

MIRRORS = ["docker.1ms.run", "docker.m.daocloud.io", "docker.xuanyuan.me", "hub.rat.dev"]
REPO = "library/python"
TAG = "3.11-slim"
PLATFORMS = [("linux", "amd64"), ("linux", "arm64")]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "base-image")

def http(url, headers=None, binary=False):
    import time
    last=None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
                return (data, dict(r.headers)) if binary else (data.decode(), dict(r.headers))
        except urllib.error.HTTPError:
            raise
        except Exception as e:
            last=e; time.sleep(3*(attempt+1))
    raise last

def get_token(mirror):
    try:
        urllib.request.urlopen(f"https://{mirror}/v2/", timeout=15)
        return None  # 无需token
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        www = e.headers.get("WWW-Authenticate", "")
        m = re.search(r'realm="([^"]+)"(?:,service="([^"]*)")?', www)
        if not m:
            raise RuntimeError(f"无法解析认证头: {www}")
        realm, service = m.group(1), m.group(2) or ""
        q = {"scope": f"repository:{REPO}:pull"}
        if service:
            q["service"] = service
        body, _ = http(realm + "?" + urllib.parse.urlencode(q))
        return json.loads(body).get("token") or json.loads(body).get("access_token")

def fetch(mirror, token, path, accept=None, binary=False):
    h = {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if accept:
        h["Accept"] = accept
    return http(f"https://{mirror}/v2/{REPO}/{path}", h, binary=binary)

MANIFEST_TYPES = ("application/vnd.oci.image.index.v1+json,"
                  "application/vnd.docker.distribution.manifest.list.v2+json,"
                  "application/vnd.oci.image.manifest.v1+json,"
                  "application/vnd.docker.distribution.manifest.v2+json")

def save_blob(blobdir, data):
    d = "sha256:" + hashlib.sha256(data).hexdigest()
    with open(os.path.join(blobdir, d.split(":")[1]), "wb") as f:
        f.write(data)
    return d, len(data)

def main():
    last_err = None
    for mirror in MIRRORS * 3:
        try:
            print(f"== 尝试镜像站 {mirror}")
            token = get_token(mirror)
            body, hdrs = fetch(mirror, token, f"manifests/{TAG}", MANIFEST_TYPES)
            idx = json.loads(body)
            if "manifests" not in idx:
                raise RuntimeError("返回的不是 manifest list")
            blobdir = os.path.join(OUT, "blobs", "sha256")
            os.makedirs(blobdir, exist_ok=True)
            new_manifests = []
            for os_, arch in PLATFORMS:
                entry = next(m for m in idx["manifests"]
                             if m.get("platform", {}).get("os") == os_
                             and m.get("platform", {}).get("architecture") == arch)
                mdig = entry["digest"]
                mbody, _ = fetch(mirror, token, f"manifests/{mdig}",
                                 "application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json")
                manifest = json.loads(mbody)
                mraw = mbody.encode()
                d, sz = save_blob(blobdir, mraw)
                mt = manifest.get("mediaType", "application/vnd.docker.distribution.manifest.v2+json")
                new_manifests.append({"mediaType": mt, "digest": d, "size": sz,
                                      "platform": {"os": os_, "architecture": arch}})
                todo = [manifest["config"]] + manifest["layers"]
                for i, blob in enumerate(todo):
                    bd = blob["digest"]
                    fp = os.path.join(blobdir, bd.split(":")[1])
                    if os.path.exists(fp):
                        continue
                    print(f"  [{arch}] blob {i+1}/{len(todo)} {blob.get('size',0)//1024//1024}MB ...")
                    data, _ = fetch(mirror, token, f"blobs/{bd}", binary=True)
                    if "sha256:" + hashlib.sha256(data).hexdigest() != bd:
                        raise RuntimeError(f"blob校验失败 {bd}")
                    with open(fp, "wb") as f:
                        f.write(data)
            index = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.index.v1+json",
                     "manifests": [dict(m, annotations={"io.containerd.image.name": f"docker.io/library/python:{TAG}",
                                                        "org.opencontainers.image.ref.name": TAG})
                                   for m in new_manifests]}
            with open(os.path.join(OUT, "index.json"), "w") as f:
                json.dump(index, f)
            with open(os.path.join(OUT, "oci-layout"), "w") as f:
                json.dump({"imageLayoutVersion": "1.0.0"}, f)
            tar_path = OUT + ".tar"
            with tarfile.open(tar_path, "w") as t:
                for name in ["oci-layout", "index.json", "blobs"]:
                    t.add(os.path.join(OUT, name), arcname=name)
            print("OK ->", tar_path)
            return
        except Exception as e:
            print(f"  {mirror} 失败: {e}")
            last_err = e
    raise SystemExit(f"所有镜像站失败: {last_err}")

main()
