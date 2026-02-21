import json
from urllib import response
import requests
from quiz_chain import get_llm
from app.schemas.user import InterestEnum

def fetch_youtube_subscriptions(access_token: str):
    """유튜브 API를 통해 유저의 구독 채널 목록을 가져옵니다."""
    url = "https://www.googleapis.com/youtube/v3/subscriptions"
    params = {
        "part": "snippet",
        "mine": True,
        "maxResults": 50,
        "order": "relevance"
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    
    response = requests.get(url, params=params, headers=headers)
    if response.status_code != 200:
        return []
    
    items = response.json().get("items", [])
    return [item["snippet"]["title"] for item in items]

# services/youtube_service.py 수정 (디버깅용)

async def analyze_interests_with_llm(channel_names: list):
    print(f"🔍 분석 시작 - 가져온 채널 수: {len(channel_names)}") # 디버깅 추가
    if not channel_names:
        print("❌ 채널 목록이 비어있어 분석을 중단합니다.")
        return None

    try:
        llm = get_llm()
        allowed_values = [e.value for e in InterestEnum]
        
        prompt = f"""
        당신은 유튜브 구독 목록을 분석하는 전문가입니다. 
        목록: {', '.join(channel_names)}
        허용 태그: {', '.join(allowed_values)}
        분석 절차:
        
        1. 각 채널이 어떤 주제인지 추론하세요.
        2. 공통 패턴을 찾으세요.
        3. 사용자의 핵심 관심사를 도출하세요.
        4. 허용 태그 중 가장 적합한 것 최대 5개 선택하세요.

        
        규칙:
        - 각 태그는 반드시 하나 이상의 채널에서 근거를 찾을 수 있어야 합니다.
        - 채널 이름에서 직접 유추 가능한 태그를 우선
        - 서로 다른 분야를 우선 선택 (다양성)
        - 확신이 높은 태그만 선택
        
        형식: {{"interests": ["태그1", "태그2"]}}
        """
        
        response = await llm.ainvoke(prompt)
        content = response.content.strip()
        print(f"🤖 LLM 응답 원본: {content}") # 디버깅 추가

        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        
        data = json.loads(content)
        valid_interests = [i for i in data.get("interests", []) if i in allowed_values][:5]
        
        print(f"✅ 최종 추출된 관심사: {valid_interests}")
        return {"interests": valid_interests}
    except Exception as e:
        print(f"🔥 분석 중 에러 발생: {str(e)}") # 에러 내용 출력
        return None