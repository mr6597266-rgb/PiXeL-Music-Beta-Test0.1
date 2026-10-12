FROM python:3.12-slim
WORKDIR /app
COPY pixel_music.py .
# все данные (база и файлы) лежат в /data, подключи сюда постоянный том/диск
ENV PIXEL_DATA=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8080
CMD ["python", "pixel_music.py"]
