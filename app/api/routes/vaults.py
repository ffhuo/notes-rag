"""API·vaults — 前端配置 vault（列表 / 创建 / 上传 / 删除 / 重建索引，均需鉴权，见 §17.2）。

能力：
- 列出当前用户的 vault
- 新建 vault（JSON）：本地目录（source_value=绝对路径）或 git/remote（source_value=URL）
- 上传 vault（multipart）：上传 .zip，服务端解压后登记为 source_type=uploaded
- 查看 / 删除 vault（删除同时清该 vault 的索引与分块）
- 触发重建索引（reindex，复用 ingest 管线）

主要端点：
- GET    /api/v1/vaults
- POST   /api/v1/vaults                 # JSON: { name, source_type: local|git|remote, source_value, filters? }
- POST   /api/v1/vaults/upload          # multipart: name + file=.zip（source_type=uploaded）
- GET    /api/v1/vaults/{id}
- DELETE /api/v1/vaults/{id}
- POST   /api/v1/vaults/{id}/reindex

注意：FastAPI 同一端点不能同时接收 Pydantic JSON body 与 UploadFile，
故「本地目录 / 远程」走 JSON 建库，「上传 zip」单独走 /upload 的 multipart。

关联方案：docs/design.md §17.2（vault 管理）、§17.4（数据模型）、§4.1（ingest 时序）。
"""
from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.database import get_session
from app.models.schemas import VaultCreate, VaultOut

router = APIRouter(prefix="/api/v1/vaults", tags=["vaults"])


@router.get("", response_model=list[VaultOut])
async def list_vaults(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    ...


@router.post("", response_model=VaultOut)
async def create_vault(
    payload: VaultCreate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    # source_type: local -> source_value 为绝对路径；git/remote -> source_value 为 URL
    ...


@router.post("/upload", response_model=VaultOut)
async def upload_vault(
    name: str = Form(...),
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    # 1) 建 vault（source_type="uploaded"）拿 vault_id
    # 2) vault_service.save_upload(vault_id, file) 解压到 UPLOAD_DIR/<vault_id>
    # 3) 回填 source_value 为该目录
    ...


@router.get("/{vault_id}", response_model=VaultOut)
async def get_vault(
    vault_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    ...


@router.delete("/{vault_id}")
async def delete_vault(
    vault_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    # 1) 校验归属 → 2) 清该 vault 的 notes/chunks（vault_repo.delete_vault）
    # 3) 清向量库（vectorstore 按 vault_id 删除）
    ...


@router.post("/{vault_id}/reindex")
async def reindex_vault(
    vault_id: int,
    rebuild: bool = False,
    embed_profile: str | None = None,   # 换 embedding 模型重建（name 或 id，见 §18.2）
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    # 1) 取 vault → model_service.resolve_profile(kind='embed', ref=embed_profile)
    # 2) vault_service.reindex(vault, rebuild, embed_profile=profile)
    #    → ingest 写入 collection_name(vault_id, profile.id) 并把 profile.id 记入 embed_indexed_profiles
    # 3) 返回 IngestResponse + 当前生效的 embed profile
    ...
