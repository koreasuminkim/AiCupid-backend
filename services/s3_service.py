# services/s3_service.py
import boto3
import os
from botocore.exceptions import NoCredentialsError

# .env 파일이나 환경 변수에서 설정값 가져오기
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "ap-northeast-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# S3 클라이언트 생성
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)

def upload_file_to_s3(file, object_name=None):
    """
    S3에 파일을 업로드하고 파일 URL을 반환합니다.
    :param file: 업로드할 파일 객체 (UploadFile)
    :param object_name: S3에 저장될 파일 이름. 지정하지 않으면 원본 파일 이름 사용.
    :return: 업로드된 파일의 URL 또는 실패 시 None
    """
    if object_name is None:
        object_name = file.filename

    try:
        s3_client.upload_fileobj(
            file.file,
            S3_BUCKET_NAME,
            object_name,
            ExtraArgs={'ContentType': file.content_type} # 파일 타입에 맞게 ContentType 설정
        )
        
        # 업로드된 파일의 URL 생성
        file_url = f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{object_name}"
        return file_url

    except FileNotFoundError:
        print("The file was not found")
        return None
    except NoCredentialsError:
        print("Credentials not available")
        return None
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

def upload_file_to_s3_raw(file_bytes, object_name, ext):
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=object_name,
            Body=file_bytes,
            ContentType=f'image/{ext}' 
        )
        return f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{object_name}"
    except Exception as e:
        print(f"S3 Raw Upload Error: {e}")
        return None