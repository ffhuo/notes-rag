"""路由·语音 — POST /api/v1/audio/transcribe（语音转文字）。

能力：
- 接收前端 MediaRecorder 录到的音频片段（multipart），转发给 kind=asr 配置的
  /audio/transcriptions 端点，返回识别文本
- 目标端点用 model_profiles(kind="asr") 解析：与 llm 共用 base_url / api_key / model
  三个字段（同一厂商的 base_url 通常同时提供 chat 与 audio），**全部取自该配置自身**。
  刻意**不新增 ASR_* 环境变量** —— 那会让「用哪个端点」出现第二处真相

主要端点：
- POST /api/v1/audio/transcribe → { text, model, elapsed_ms }

设计取舍：
- **不落库**：一次请求一次转发，音频不写磁盘，也不记录识别结果（用户会在输入框改错字后
  自己发出；留下原始音频只是多一份需要长期看管的隐私数据）
- **不流式**：识别结果一次性返回，由前端填进输入框 —— 一期不做「边说边出字」
- **不静默回退**：没有 asr 配置时返回 409 并提示去模型页添加。把语音请求发给 chat 端点
  只会换回一个难懂的 400，不如直接说清楚缺什么

鉴权：只用 get_current_user_id（不要再叠加 get_current_api_key，见 conversations.py 同注）。

关联方案：docs/design.md §18（多模型管理）、§4.3（Chat）。
"""
import time

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_session, get_settings
from app.core.config import Settings
from app.models.schemas import TranscribeOut
from app.rag.client import build_client
from app.services import model_service
from app.services.model_service import ModelNotConfigured, ModelNotFound, to_runtime

router = APIRouter(prefix="/api/v1/audio", tags=["audio"])


@router.post("/transcribe", response_model=TranscribeOut)
async def transcribe(
    file: UploadFile = File(..., description="音频文件（webm/opus、mp4/aac、wav 等）"),
    language: str | None = Query(None, description="识别语言，如 zh / en；留空由模型自判"),
    prompt: str | None = Query(None, description="热词提示，如笔记里的专有名词"),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """把一段音频转成文字。"""
    try:
        profile = await model_service.resolve_profile(session, settings, "asr", user_id=user_id)
    except ModelNotConfigured:
        raise HTTPException(
            status_code=409,
            detail="尚未配置语音识别模型：请到「模型」页新增一个 kind=asr 的配置",
        )
    except ModelNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))

    runtime = to_runtime(profile)

    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="音频内容为空")

    # 文件名要带扩展名：上游多半按它推断容器格式；前端理论上总会给，这里兜一个
    filename = file.filename or "clip.webm"
    # SDK 的 multipart 需要 (文件名, 二进制, MIME) 三元组
    upload = (filename, data, file.content_type or "audio/webm")

    kwargs: dict = {"model": runtime.model, "file": upload}
    if language:
        kwargs["language"] = language
    if prompt:
        kwargs["prompt"] = prompt

    start = time.monotonic()
    try:
        result = await build_client(runtime).audio.transcriptions.create(**kwargs)
    except Exception as e:
        # 上游报错原样透出：识别失败的原因（模型名不对 / 格式不收 / 配额）都在里面，
        # 吞掉换成「转写失败」会让用户和我们都没法定位
        logger.warning("语音识别失败 model={} err={}", runtime.model, e)
        raise HTTPException(status_code=502, detail=f"语音识别失败：{e}")

    elapsed = int((time.monotonic() - start) * 1000)
    # 兼容两种返回：对象带 .text，或（部分兼容实现）直接给字典
    text = result.get("text") if isinstance(result, dict) else getattr(result, "text", "")
    return TranscribeOut(text=str(text or "").strip(), model=runtime.model, elapsed_ms=elapsed)