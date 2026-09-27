"""路由·语音 — POST /api/v1/audio/transcribe（语音转文字）。

能力：
- 接收前端 MediaRecorder 录到的音频片段（multipart），按 kind=asr 配置转发给上游，返回识别文本
- 两套协议二选一，由 params.protocol 决定（见模块内协议标记注释）：
  · OpenAI ASR（默认）：multipart 打到 /audio/transcriptions
  · DashScope 原生：Base64 Data URL 打到 multimodal-generation 端点（百炼 Qwen-Audio-3.x-ASR-Flash）
- 目标端点用 model_profiles(kind="asr") 解析：与 llm 共用 base_url / api_key / model
  三个字段，**全部取自该配置自身**。
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
import base64
import time

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_session
from app.models.schemas import TranscribeOut
from app.rag.client import build_client
from app.services import model_service
from app.services.model_service import ModelNotConfigured, ModelNotFound, to_runtime

router = APIRouter(prefix="/api/v1/audio", tags=["audio"])

# 协议标记：params_json.protocol 为该值时走 DashScope 原生同步调用，其余（含缺省）按 OpenAI ASR 走。
# 它只影响**怎么调**，不影响用哪个模型 —— 故不新增 kind、不新增 DB 列。
_PROTOCOL_DASHSCOPE = "dashscope_native"
_DASHSCOPE_PATH = "/api/v1/services/aigc/multimodal-generation/generation"

# parameters.format 用它把上传的 MIME 映射成贴切的容器名。实测该值不被校验、服务端按音频字节
# 自行判断容器，但字段**不能为空**，否则一律回 400 UNSUPPORTED_FORMAT「format is empty」。
_FMT_BY_MIME = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg"}


def _base_mime(raw: str | None) -> str:
    """'audio/webm;codecs=opus' → 'audio/webm'：Data URL 的 mediatype 只认主类型。"""
    return (raw or "audio/webm").split(";")[0].strip() or "audio/webm"


def _dashscope_native_url(base_url: str) -> str:
    """把模型配置里的 OpenAI 兼容端点换成 DashScope 原生端点。

    Qwen-Audio-3.x-ASR-Flash 不在兼容模式的白名单里（实测 404 Unsupported model），
    只能在原生端点调，故剥掉 /compatible-mode/v1 只取 origin 再拼原生路径。
    """
    base = (base_url or "").rstrip("/")
    suffix = "/compatible-mode/v1"
    if base.endswith(suffix):
        base = base[: -len(suffix)]
    return base + _DASHSCOPE_PATH


def _pick_native_text(payload: dict) -> str:
    """取原生同步接口的识别文本。

    该接口返回结构与 OpenAI 不同（官方明确提示无 choices 字段）：文本在 output.text，
    个别情况下只在 output.output.sentence.text，故两个位置都兜一下。
    """
    out = payload.get("output")
    if not isinstance(out, dict):
        return ""
    if out.get("text"):
        return str(out["text"])
    inner = out.get("output")
    if isinstance(inner, dict):
        sentence = inner.get("sentence")
        if isinstance(sentence, dict) and sentence.get("text"):
            return str(sentence["text"])
    return ""


async def _transcribe_openai_asr(client, runtime, upload, language, prompt) -> str:
    """OpenAI ASR 协议：multipart 上传文件，取返回的 text。"""
    kwargs: dict = {"model": runtime.model, "file": upload}
    if language:
        kwargs["language"] = language
    if prompt:
        kwargs["prompt"] = prompt

    result = await client.audio.transcriptions.create(**kwargs)
    # 兼容两种返回：对象带 .text，或（部分兼容实现）直接给字典
    text = result.get("text") if isinstance(result, dict) else getattr(result, "text", "")
    return str(text or "")


async def _transcribe_dashscope_native(runtime, data: bytes, mime: str) -> str:
    """DashScope 原生同步调用（百炼 Qwen-Audio-3.x-ASR-Flash）。

    与 OpenAI ASR 的三处差异：
    - 端点是原生 /api/v1/services/aigc/multimodal-generation/generation，
      不是 OpenAI 兼容的 /chat/completions（该系列模型在兼容模式下直接 404）
    - 音频不走 multipart，而是 `data:<mime>;base64,<...>` 塞进 input_audio.data
    - parameters.format 为必填非空字段（实测值本身不被校验，服务端按音频字节判断容器），
      sample_rate 可省略且不影响解码，故这里只给一个贴切的容器名

    识别语言 / 热词：原生同步接口未提供对应参数，故本协议忽略 language 与 prompt。
    """
    if not runtime.base_url:
        raise RuntimeError("kind=asr 配置缺少 base_url：DashScope 原生协议需要百炼端点")

    data_url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    payload = {
        "model": runtime.model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_audio", "input_audio": {"data": data_url}}
                    ],
                }
            ]
        },
        "parameters": {"format": _FMT_BY_MIME.get(mime, "webm")},
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            _dashscope_native_url(runtime.base_url),
            json=payload,
            headers={
                "Authorization": f"Bearer {runtime.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
        )
    if resp.status_code != 200:
        # 上游的 code/message 是定位关键（模型名不对、端点不对都在这句话里），原样透出
        raise RuntimeError(f"HTTP {resp.status_code} {resp.text[:300]}")
    return _pick_native_text(resp.json())


@router.post("/transcribe", response_model=TranscribeOut)
async def transcribe(
    file: UploadFile = File(..., description="音频文件（webm/opus、mp4/aac、wav 等）"),
    language: str | None = Query(None, description="识别语言，如 zh / en；留空由模型自判"),
    prompt: str | None = Query(None, description="热词提示，如笔记里的专有名词"),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """把一段音频转成文字。"""
    try:
        profile = await model_service.resolve_profile(session, "asr", user_id=user_id)
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

    start = time.monotonic()
    try:
        # 两条协议二选一，由 params.protocol 决定（见模块内协议标记注释）
        if runtime.params.get("protocol") == _PROTOCOL_DASHSCOPE:
            text = await _transcribe_dashscope_native(
                runtime, data, _base_mime(file.content_type)
            )
        else:
            # 文件名要带扩展名：上游多半按它推断容器格式；前端理论上总会给，这里兜一个
            filename = file.filename or "clip.webm"
            # SDK 的 multipart 需要 (文件名, 二进制, MIME) 三元组
            upload = (filename, data, file.content_type or "audio/webm")
            client = build_client(runtime)
            text = await _transcribe_openai_asr(client, runtime, upload, language, prompt)
    except Exception as e:
        # 上游报错原样透出：识别失败的原因（模型名不对 / 格式不收 / 配额）都在里面，
        # 吞掉换成「转写失败」会让用户和我们都没法定位
        logger.warning("语音识别失败 model={} err={}", runtime.model, e)
        raise HTTPException(status_code=502, detail=f"语音识别失败：{e}")

    elapsed = int((time.monotonic() - start) * 1000)
    return TranscribeOut(text=str(text or "").strip(), model=runtime.model, elapsed_ms=elapsed)