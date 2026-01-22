# Golf Travel Agent - Docker Image
# 基于 Python 3.11 slim 镜像，使用 uv 管理依赖

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖（curl 用于健康检查）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN pip install --no-cache-dir uv

# 复制依赖文件（README.md 是 pyproject.toml 的 readme 依赖）
COPY pyproject.toml uv.lock README.md ./

# 安装 Python 依赖（不包含开发依赖）
RUN uv sync --frozen --no-dev

# 复制源代码
COPY src/ src/

# 设置 PYTHONPATH
ENV PYTHONPATH=/app/src

# 创建数据目录（用于持久化）
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 8080

# 健康检查（AsyncSqliteSaver 初始化需要较长启动时间）
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=5 \
    CMD curl -f http://localhost:8080/health || exit 1

# 启动命令
CMD ["uv", "run", "python", "-m", "travel_agent.server"]
