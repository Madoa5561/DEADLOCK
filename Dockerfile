FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY arena arena
COPY static static
COPY app.py manage.py ./
RUN useradd --create-home arena && mkdir /data && chown arena:arena /data
USER arena
ENV DEADLOCK_HOST=0.0.0.0 DEADLOCK_DB=/data/arena.sqlite3
EXPOSE 8000
VOLUME ["/data"]
CMD ["python", "app.py"]
