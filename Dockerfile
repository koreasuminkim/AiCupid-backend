# Python 3.11을 기반으로 하는 공식 이미지를 사용합니다.
FROM python:3.11-slim

# 작업 디렉토리를 /app으로 설정합니다.
WORKDIR /app

# uv를 설치합니다.
RUN pip install uv

# requirements.txt를 복사하고 uv를 사용하여 의존성을 설치합니다.
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# 프로젝트의 나머지 파일을 복사합니다.
COPY . .

# 8000번 포트를 외부에 노출합니다.
EXPOSE 8000

# uv를 사용하여 uvicorn으로 애플리케이션을 실행합니다.
CMD ["uv", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]