from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.output_parsers.json import JsonOutputParser
import json

# LLM 모델 초기화 (창의적인 질문 생성을 위해 temperature를 약간 높임)
llm = ChatGoogleGenerativeAI(model="gemini-pro", temperature=0.7)

# --- 퀴즈 진행 및 채점을 위한 도구(Tool) 정의 ---

class QuestionProvider(BaseModel):
    """사용자의 이전 대화 기록을 바탕으로 새로운 퀴즈 질문과 정답을 생성합니다."""
    history: list = Field(description="전체 대화 기록")

    def get_question(self) -> dict:
        """LLM을 사용하여 새로운 질문과 정답을 생성하고 JSON으로 반환합니다."""
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """당신은 창의적인 퀴즈 출제자입니다. 사용자와의 이전 대화 내용을 바탕으로, 개인화된 새로운 퀴즈를 만들어주세요.
                    
                    - 이전 대화에서 언급된 주제나 단어를 활용하여 질문을 만드세요.
                    - 하지만 이전에 출제했던 질문과 똑같은 질문은 절대 만들면 안 됩니다.
                    - 반드시 질문(question)과 정답(answer)을 포함하는 JSON 형식으로만 응답해주세요.
                    - 예시: {{"question": "세상에서 가장 높은 산은 무엇인가요?", "answer": "에베레스트 산"}}
                    """,
                ),
                ("user", "이전 대화 내용: {history}\n\n위 대화 내용과 관련있는 새로운 퀴즈를 하나 만들어줘."),
            ]
        )
        
        # JSON 출력을 위한 체인 구성
        chain = prompt | llm | JsonOutputParser()
        
        # LLM이 유효한 JSON을 생성할 때까지 몇 번 재시도
        for _ in range(3):
            try:
                response = chain.invoke({"history": self.history})
                if "question" in response and "answer" in response:
                    return response
            except (json.JSONDecodeError, TypeError):
                print("Warning: Failed to decode JSON from LLM, retrying...")
                continue
        
        # 재시도 실패 시 기본 질문 반환
        return {"question": "대한민국의 수도는 어디인가요?", "answer": "서울"}


class QuizGrader(BaseModel):
    """사용자의 답변이 주어진 정답과 일치하는지 채점합니다."""
    user_answer: str = Field(description="사용자의 답변")
    question: str = Field(description="채점할 질문")
    correct_answer: str = Field(description="미리 생성된 정답")
    
    def grade(self) -> bool:
        """LLM을 사용하여 사용자의 답변을 채점하고 정답 여부를 반환합니다."""
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "당신은 퀴즈 채점 전문가입니다. 사용자의 답변이 주어진 질문의 정답과 의미적으로 일치하는지 판단해주세요. '정답' 또는 '오답'으로만 대답해야 합니다.",
                ),
                (
                    "user",
                    "질문: '{question}'\n정답: '{correct_answer}'\n사용자 답변: '{user_answer}'\n\n이 답변은 정답인가요, 오답인가요?",
                ),
            ]
        )
        chain = prompt | llm
        response = chain.invoke({
            "question": self.question,
            "correct_answer": self.correct_answer,
            "user_answer": self.user_answer
        })
        
        # LLM의 응답에 '정답'이 포함되어 있는지 여부로 판단
        return "정답" in response.content
