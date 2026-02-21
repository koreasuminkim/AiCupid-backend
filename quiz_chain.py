from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

# LLM은 첫 사용 시에만 생성 (langgraph dev 로드 시 GEMINI_API_KEY 없어도 그래프 구조는 로드됨)
_llm = None


def get_llm():
    global _llm
    if _llm is None:
        from dotenv import load_dotenv
        load_dotenv()
        _llm = ChatGoogleGenerativeAI(model="gemini-pro", temperature=0)
    return _llm

# 퀴즈 질문과 정답 데이터
quiz_data = [
    {"question": "대한민국의 수도는 어디인가요?", "answer": "서울"},
    {"question": "세상에서 가장 높은 산은 무엇인가요?", "answer": "에베레스트"},
    {"question": "미국의 초대 대통령은 누구인가요?", "answer": "조지 워싱턴"},
]

# --- 퀴즈 진행 및 채점을 위한 도구(Tool) 정의 ---

class QuizGrader(BaseModel):
    """사용자의 답변이 퀴즈의 정답과 일치하는지 채점합니다."""
    user_answer: str = Field(description="사용자의 답변")
    question_id: int = Field(description="현재 질문의 ID")
    
    def grade(self) -> bool:
        """정답이면 True, 오답이면 False를 반환합니다."""
        correct_answer = quiz_data[self.question_id]["answer"]
        return self.user_answer.strip() == correct_answer

class QuestionProvider(BaseModel):
    """다음 퀴즈 질문을 제공합니다."""
    question_id: int = Field(description="제공할 질문의 ID")

    def get_question(self) -> str:
        """해당 ID의 질문을 반환합니다."""
        if self.question_id < len(quiz_data):
            return quiz_data[self.question_id]["question"]
        return "모든 퀴즈가 종료되었습니다."

# --- LangChain을 이용한 체인 정의 ---

# 사용자의 답변을 평가(채점)하기 위한 프롬프트 및 체인
grade_answer_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "당신은 퀴즈 채점 전문가입니다. 사용자의 답변 '{user_answer}'가 질문 '{question}'의 정답 '{correct_answer}'와 일치하는지 판단해주세요. '정답' 또는 '오답'으로만 대답해주세요.",
        ),
    ]
)

def get_grading_chain():
    return grade_answer_prompt | get_llm()

# 다음 행동을 결정하기 위한 프롬프트 및 체인
# 이 체인은 LLM이 다음에 어떤 도구(QuizGrader, QuestionProvider)를 사용해야 할지 결정하도록 합니다.
react_prompt = """당신은 대화의 흐름을 관리하는 AI 에이전트입니다. 
대화 기록과 사용 가능한 도구를 바탕으로 다음에 어떤 행동을 해야 할지 결정하세요.

사용 가능한 도구:
- QuizGrader: 사용자의 답변을 채점합니다.
- QuestionProvider: 다음 질문을 물어봅니다.

대화 기록:
{messages}

현재 퀴즈 상태:
- 현재 질문 ID: {question_id}
- 점수: {score}

사용자의 최근 입력: "{last_message}"

위 정보를 바탕으로, 다음에 호출해야 할 도구와 그 도구에 전달할 인자를 JSON 형식으로 응답해주세요.
만약 더 이상 진행할 퀴즈가 없다면 "finished"라고 응답하세요.
일반적인 대화라면 "chat"이라고 응답하세요.
"""

def get_react_chain():
    return ChatPromptTemplate.from_template(react_prompt) | get_llm()
