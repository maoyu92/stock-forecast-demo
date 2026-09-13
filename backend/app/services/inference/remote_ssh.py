"""远程 TimesFM 引擎：经 SSH 到局域网 GPU 服务器，驱动常驻 worker

worker 协议（JSON Lines over ssh exec 通道）：
  请求: {"id": N, "context": [...], "horizon": H, "past_only": [[..]]|null,
         "return_quantiles": bool, "make_positive": bool}
  响应: {"id": N, "ok": true, "forecast": [...], "quantiles": [[..]]|null}
        {"id": N, "ok": false, "error": "..."}
worker 启动时先输出一行 READY（模型加载完成后）。
"""
import hashlib
import json
import logging
import socket
import threading
import time
from pathlib import Path

import numpy as np

from ... import config
from .base import BaseEngine, InferenceError, InferenceResult, extract_band

log = logging.getLogger("remote-timesfm")

# worker 脚本随 backend 一起分发：backend/inference-worker/infer_service.py
WORKER_LOCAL_PATH = Path(__file__).resolve().parents[3] / "inference-worker" / "infer_service.py"


def default_key_path() -> str:
    if config.TIMESFM_SSH_KEY_PATH:
        return config.TIMESFM_SSH_KEY_PATH
    candidate = Path.home() / ".ssh" / "id_ed25519"
    return str(candidate) if candidate.exists() else ""


def is_tcp_reachable(timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((config.TIMESFM_SSH_HOST, config.TIMESFM_SSH_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def ssh_handshake_ok(timeout: float = 6.0) -> bool:
    """完整 SSH 认证探测（比 TCP 更准确）"""
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = _ssh_kwargs(timeout)
        client.connect(config.TIMESFM_SSH_HOST, port=config.TIMESFM_SSH_PORT,
                       username=config.TIMESFM_SSH_USER, **kwargs)
        client.close()
        return True
    except Exception as e:
        log.info("SSH handshake 失败: %s", e)
        return False


def _ssh_kwargs(timeout: float) -> dict:
    kwargs: dict = {"timeout": timeout, "banner_timeout": timeout,
                    "auth_timeout": timeout, "look_for_keys": True, "allow_agent": True}
    key = default_key_path()
    if key:
        kwargs["key_filename"] = key
    if config.TIMESFM_SSH_PASSWORD:
        kwargs["password"] = config.TIMESFM_SSH_PASSWORD
    return kwargs


class RemoteSSHEngine(BaseEngine):
    name = "remote"

    def __init__(self):
        self._lock = threading.Lock()
        self._client = None
        self._stdin = self._stdout = None
        self._ready = False
        self._req_seq = 0

    # ---------- 连接与部署 ----------

    def _connect(self) -> None:
        import paramiko
        self._close()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(config.TIMESFM_SSH_HOST, port=config.TIMESFM_SSH_PORT,
                       username=config.TIMESFM_SSH_USER, **_ssh_kwargs(8.0))
        client.get_transport().set_keepalive(30)
        self._deploy_worker(client)
        # 启动常驻 worker（模型只加载一次）
        cmd = (f"mkdir -p {config.TIMESFM_REMOTE_DIR} && "
               f"cd {config.TIMESFM_REMOTE_DIR} && "
               f"{config.TIMESFM_REMOTE_PYTHON} -u infer_service.py")
        self._stdin, self._stdout, _ = client.exec_command(cmd, timeout=None)
        self._stdout.channel.settimeout(600)
        t0 = time.time()
        while True:
            line = self._stdout.readline()
            if not line:
                raise InferenceError("GPU 服务器 worker 启动失败（通道关闭）")
            if line.strip() == "READY":
                break
            log.info("[worker] %s", line.strip())
            if time.time() - t0 > 300:
                raise InferenceError("GPU 服务器模型加载超时（>300s）")
        self._client = client
        self._ready = True
        log.info("远程 worker 就绪 (%s:%s)", config.TIMESFM_SSH_HOST, config.TIMESFM_SSH_PORT)

    def _deploy_worker(self, client) -> None:
        """校验远端 worker 与本地一致，不一致则 SFTP 上传"""
        local = WORKER_LOCAL_PATH
        if not local.exists():
            raise InferenceError(f"找不到 worker 脚本: {local}")
        local_sha = hashlib.sha256(local.read_bytes()).hexdigest()
        remote_path = f"{config.TIMESFM_REMOTE_DIR}/infer_service.py"
        _, stdout, _ = client.exec_command(
            f"mkdir -p {config.TIMESFM_REMOTE_DIR} && "
            f"sha256sum {remote_path} 2>/dev/null | cut -d' ' -f1")
        remote_sha = stdout.read().decode().strip()
        if remote_sha == local_sha:
            return
        sftp = client.open_sftp()
        try:
            sftp.put(str(local), remote_path)
            log.info("worker 脚本已上传到 %s:%s", config.TIMESFM_SSH_HOST, remote_path)
        finally:
            sftp.close()

    def _close(self) -> None:
        self._ready = False
        if self._stdout is not None:
            try:
                self._stdout.channel.close()
            except Exception:
                pass
        self._stdin = self._stdout = None
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None

    # ---------- 推理 ----------

    def predict(self, context, horizon, past_only=None,
                return_quantiles=True, make_positive=True) -> InferenceResult:
        with self._lock:
            for attempt in (1, 2):  # 断线自动重连一次
                try:
                    if not self._ready:
                        self._connect()
                    return self._do_predict(context, horizon, past_only,
                                            return_quantiles, make_positive)
                except InferenceError:
                    if attempt == 2:
                        raise
                    log.warning("远程推理失败，重连重试…", exc_info=True)
                    self._close()
                except Exception:
                    self._close()
                    if attempt == 2:
                        raise
                    log.warning("远程通道异常，重连重试…", exc_info=True)
        raise InferenceError("unreachable")

    def _do_predict(self, context, horizon, past_only,
                    return_quantiles, make_positive) -> InferenceResult:
        self._req_seq += 1
        req_id = self._req_seq
        payload = {
            "id": req_id,
            "context": np.asarray(context, dtype=np.float64).tolist(),
            "horizon": int(horizon),
            "past_only": np.asarray(past_only, dtype=np.float64).tolist() if past_only is not None else None,
            "return_quantiles": bool(return_quantiles),
            "make_positive": bool(make_positive),
        }
        try:
            self._stdin.write(json.dumps(payload) + "\n")
            self._stdin.flush()
        except Exception as e:
            raise InferenceError(f"发送请求失败: {e}")

        deadline = time.time() + 300
        while time.time() < deadline:
            line = self._stdout.readline()
            if not line:
                raise InferenceError("worker 通道已关闭")
            line = line.strip()
            if not line or not line.startswith("{"):
                log.info("[worker] %s", line)  # 忽略日志行
                continue
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue
            if resp.get("id") != req_id:
                continue
            if not resp.get("ok"):
                raise InferenceError(f"GPU 推理失败: {resp.get('error')}")
            forecast = np.asarray(resp["forecast"], dtype=np.float64)
            q_lower = q_upper = None
            if resp.get("quantiles"):
                q_lower, q_upper = extract_band(resp["quantiles"],
                                                config.QUANTILE_LOW_IDX, config.QUANTILE_HIGH_IDX)
            return InferenceResult(forecast=forecast, q_lower=q_lower, q_upper=q_upper,
                                   mode="remote",
                                   detail=f"远程 GPU {config.TIMESFM_SSH_HOST} (TimesFM 3.0)")
        raise InferenceError("GPU 推理超时（>300s）")

    def status(self) -> dict:
        tcp = is_tcp_reachable()
        info = {"name": "remote", "host": config.TIMESFM_SSH_HOST,
                "tcp_reachable": tcp, "worker_ready": self._ready}
        if not tcp:
            info["available"] = False
            info["detail"] = "服务器不可达"
            return info
        ssh_ok = ssh_handshake_ok()
        info["available"] = bool(ssh_ok or self._ready)
        info["detail"] = "SSH 认证通过" if ssh_ok else (
            "worker 已连接" if self._ready else "SSH 认证失败（检查密钥/fail2ban）")
        return info
