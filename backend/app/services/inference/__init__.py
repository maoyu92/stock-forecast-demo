"""推理引擎工厂与回退链"""
import logging

from ... import config
from .base import BaseEngine, InferenceError, InferenceResult
from .mock import MockEngine

log = logging.getLogger("inference")

__all__ = ["BaseEngine", "InferenceError", "InferenceResult", "get_engine", "engine_status"]

_mock_engine = MockEngine()
_remote_engine = None
_local_engine = None


def _get_remote():
    global _remote_engine
    if _remote_engine is None:
        from .remote_ssh import RemoteSSHEngine
        _remote_engine = RemoteSSHEngine()
    return _remote_engine


def _get_local():
    global _local_engine
    if _local_engine is None:
        from .local_timesfm import LocalTimesFMEngine
        _local_engine = LocalTimesFMEngine()
    return _local_engine


def get_engine() -> BaseEngine:
    """按配置返回首选引擎（预测编排器会自行处理回退）"""
    mode = config.INFERENCE_MODE
    if mode == "remote":
        return _get_remote()
    if mode == "local":
        return _get_local()
    if mode == "mock":
        return _mock_engine
    # auto：SSH 认证可用 → remote；否则本地 timesfm；否则 mock
    from .remote_ssh import ssh_handshake_ok
    from .local_timesfm import is_importable
    if ssh_handshake_ok():
        return _get_remote()
    if is_importable():
        return _get_local()
    return _mock_engine


def engine_candidates() -> list[BaseEngine]:
    """auto 模式下的回退顺序"""
    mode = config.INFERENCE_MODE
    if mode == "remote":
        return [_get_remote()]
    if mode == "local":
        return [_get_local()]
    if mode == "mock":
        return [_mock_engine]
    return [_get_remote(), _get_local(), _mock_engine]


def engine_status() -> dict:
    """各引擎健康状态（health 接口用）"""
    from .local_timesfm import is_importable
    from .remote_ssh import is_tcp_reachable

    out: dict = {"configured_mode": config.INFERENCE_MODE, "engines": {}}
    # remote
    remote_info: dict = {"name": "remote", "host": config.TIMESFM_SSH_HOST}
    if is_tcp_reachable():
        try:
            remote_info.update(_get_remote().status())
        except Exception as e:
            remote_info.update(available=False, detail=f"状态获取失败: {e}")
    else:
        remote_info.update(available=False, detail="服务器不可达")
    out["engines"]["remote"] = remote_info
    # local
    try:
        out["engines"]["local"] = _get_local().status()
    except Exception as e:
        out["engines"]["local"] = {"name": "local", "available": False, "detail": str(e)}
    else:
        if not is_importable():
            out["engines"]["local"]["available"] = False
    # mock
    out["engines"]["mock"] = _mock_engine.status()
    return out
