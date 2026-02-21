from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers.json import JsonOutputParser
from langchain_core.pydantic_v1 import BaseModel, Field
import json
from typing import List, Dict

# LLM 모델 초기화
llm = ChatGoogleGenerativeAI(model="gemini-pro", temperature=0.7)

class TestQuestionGenerator(BaseModel):
    """두 사람의 관계와 성향을 알아보기 위한 심리테스트 질문 3개를 생성합니다."""
    history: List[Dict[str, str]] = Field(description="이전 대화 기록")

    def generate_questions(self) -> List[str]:
        """LLM을 사용하여 질문 리스트를 생성하고 반환합니다."""
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """당신은 연인 관계나 두 사람의 케미를 알아볼 수 있는 창의적인 심리테스트 출제자입니다.
                    서로에 대해 더 깊이 이해할 수 있는 흥미로운 질문 3개를 순서대로 제시해야 합니다.
                    질문들은 반드시 JSON 형식의 배열(array)로만 응답해주세요.
                    
                    예시:
                    [
                        "함께 떠나는 여행, 비행기가 갑자기 낯선 무인도에 불시착했습니다. 가장 먼저 할 행동은 무엇인가요?",
                        "무인도에서 신비한 과일을 발견했습니다. 어떤 모양과 색깔의 과일인가요?",
                        "탐험 중 동굴을 발견했고, 그 안에서 잠들어있는 동물을 만났습니다. 어떤 동물이었나요?"
                    ]
                    """,
                ),
                ("user", "이전 대화 내용: {history}\n\n위 대화를 바탕으로, 두 사람을 위한 심리테스트 질문 3개를 JSON 배열 형태로 만들어줘."),
            ]
        )
        
        chain = prompt | llm | JsonOutputParser()
        
        for _ in range(3): # LLM이 가끔 잘못된 형식을 반환할 경우를 대비한 재시도
            try:
                response = chain.invoke({"history": self.history})
                if isinstance(response, list) and len(response) == 3:
                    return response
            except (json.JSONDecodeError, TypeError):
                continue
        
        # 재시도 실패 시 기본 질문 반환
        return [
            "함께 떠나는 여행, 비행기가 갑자기 낯선 무인도에 불시착했습니다. 가장 먼저 할 행동은 무엇인가요?",
            "무인도에서 신비한 과일을 발견했습니다. 어떤 모양과 색깔의 과일인가요?",
            "탐험 중 동굴을 발견했고, 그 안에서 잠들어있는 동물을 만났습니다. 어떤 동물이었나요?"
        ]

class TestResultAnalyzer(BaseModel):
    """모든 질문과 두 사람의 답변을 종합하여 심리테스트 결과를 분석합니다."""
    questions: List[str] = Field(description="제시되었던 심리테스트 질문 목록")
    answers: List[Dict[str, str]] = Field(description="각 질문에 대한 두 사람(p1, p2)의 답변 목록")

    def analyze(self) -> str:
        """LLM을 사용하여 종합적인 관계 분석 결과를 생성합니다."""
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """당신은 커플 관계 및 심리 분석 전문가입니다.
                    주어진 심리테스트 질문과 두 사람의 답변을 종합적으로 분석하여, 두 사람의 성향, 가치관, 관계의 특징, 그리고 서로를 위한 조언을 담은 흥미로운 결과지를 작성해주세요.
                    결과는 친근하고 다정한 말투로 작성해야 합니다.
                    """,
                ),
                ("user", "심리테스트 질문: {questions}\n\n두 사람의 답변: {answers}\n\n위 내용을 바탕으로 종합적인 심리테스트 결과지를 작성해줘."),
            ]
        )
        
        chain = prompt | llm
        response = chain.invoke({"questions": self.questions, "answers": self.answers})
        return response.content