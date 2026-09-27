FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# 会话密钥自动生成于 /app/data/secret.key（挂载卷持久化，请随数据一起备份）
ENV SLYS_HOST=0.0.0.0 SLYS_PORT=8098
EXPOSE 8098
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8098/healthz',timeout=4).status==200 else 1)"
CMD ["python", "app.py"]
