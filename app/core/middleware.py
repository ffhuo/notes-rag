"""
中间件模块
"""
import uuid
import time
from typing import Callable

from loguru import logger

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware

class LoggingMiddleware(BaseHTTPMiddleware):
    """
    请求记录中间件
    
    负责为每个请求生成唯一的 request_id，并记录请求的基本信息和耗时。
    使用 structlog.contextvars 确保 request_id 在该请求的所有后续日志中自动携带。
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        
        # 将 request_id 清理并存入 loguru 的上下文变量中
        # 这样在同一个异步任务链条中调用的所有 logger 都会自动带上这个 ID
        logger.bind(request_id=request_id)
        
        start_time = time.time()
        
        # 记录请求进入
        logger.info(
            "HTTP Request Started",
            method=request.method,
            path=request.url.path,
            query_params=str(request.query_params),
            client_host=request.client.host if request.client else "unknown",
        )

        try:
            response = await call_next(request)

            process_time = time.time() - start_time

            # 将 request_id 放入响应头中，方便前端/联调追溯
            response.headers["X-Request-ID"] = request_id
            
            # 记录请求结束
            logger.info(
                "HTTP Request Completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration=f"{process_time:.4f}s",
            )
            
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.exception(
                "HTTP Request Failed",
                method=request.method,
                path=request.url.path,
                error=str(e),
                duration=f"{process_time:.4f}s",
            )
            raise e
        