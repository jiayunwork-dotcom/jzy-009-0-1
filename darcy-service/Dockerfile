FROM python:3.11-slim

# 仅安装运行期最小系统依赖（psycopg2-binary 自带 libpq，无需额外编译工具链）
# 以非 root 用户运行。
WORKDIR /srv

COPY requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app /srv/app
COPY entrypoint.sh /srv/entrypoint.sh
RUN chmod +x /srv/entrypoint.sh && useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
ENTRYPOINT ["/srv/entrypoint.sh"]
