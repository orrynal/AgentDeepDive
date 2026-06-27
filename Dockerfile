# 使用官方轻量 Python 3.11 运行环境作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量，防止 Python 写入 .pyc 且能无缓冲实时输出日志
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 安装系统运行依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖定义与文档说明（包构建所需）
COPY pyproject.toml README.md ./

# 使用 pip 升级并强行指定安装 CPU 版本的轻量级 PyTorch，避免拉取数 GB 的 CUDA 驱动包
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir .

# 复制项目代码
COPY src/ ./src/

# 创建非特权用户并修改工作目录所有权
RUN useradd -u 10001 -m appuser && chown -R appuser:appuser /app
USER appuser

# 暴露 FastAPI 运行端口
EXPOSE 8000

# 默认启动命令（可在 K8s / Compose 部署中被 CMD 覆盖以运行 Celery Worker）
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
